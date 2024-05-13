import json
from tqdm import tqdm
from time import sleep
from datetime import datetime, timedelta


def get_lb_hourly_costs(session):
    client = session.client("pricing", region_name="us-east-1")

    net_params = {
        "ServiceCode": "AmazonEC2",
        "Filters": [
            {
                "Type": "TERM_MATCH",
                "Field": "productFamily",
                "Value": "Load Balancer-Network",
            }
        ],
    }

    app_params = {
        "ServiceCode": "AmazonEC2",
        "Filters": [
            {
                "Type": "TERM_MATCH",
                "Field": "productFamily",
                "Value": "Load Balancer-Application",
            }
        ],
    }

    # classic_params = {
    #     "ServiceCode": "AmazonEC2",
    #     "Filters": [{"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Load Balancer"}],
    # }

    net_response = client.get_products(**net_params)
    app_response = client.get_products(**app_params)
    # classic_response = client.get_products(**classic_params)

    hourly_costs = {"network": {}, "application": {}}  # , "classic": {}}
    responses = {
        "network": net_response,
        "application": app_response,
    }  # , "classic": classic_response}

    for response in responses:
        for product in responses[response]["PriceList"]:
            data = json.loads(product)

            product_key = list(data["terms"]["OnDemand"].keys())[0]
            price_dimensions_key = list(
                data["terms"]["OnDemand"][product_key]["priceDimensions"].keys()
            )[0]

            if (
                data["terms"]["OnDemand"][product_key]["priceDimensions"][
                    price_dimensions_key
                ]["unit"]
                != "Hrs"
            ):
                continue

            region = data["product"]["attributes"]["regionCode"]
            ppu = data["terms"]["OnDemand"][product_key]["priceDimensions"][
                price_dimensions_key
            ]["pricePerUnit"]

            if region not in hourly_costs[response]:
                hourly_costs[response][region] = ppu

    return hourly_costs


def delete_tgs(session, tgs, dry_run=False):
    elb_client = session.client("elbv2")

    pbar = tqdm(tgs)
    for tg_arn in pbar:
        if not dry_run:
            try:
                elb_client.delete_target_group(TargetGroupArn=tg_arn)
            except Exception as e:
                pbar.write(f"Failed to delete target group {tg_arn} with error {e}")
        pbar.write(f"deleted target group {tg_arn} (dry run: {dry_run})")

    return None


def disable_lb_deletion_protection(client, lb_arn):
    client.modify_load_balancer_attributes(
        LoadBalancerArn=lb_arn,
        Attributes=[{"Key": "deletion_protection.enabled", "Value": "false"}],
    )


def delete_lbs(session, lbs, dry_run=False):
    elb_client = session.client("elbv2")
    waiter = elb_client.get_waiter("load_balancers_deleted")

    pbar = tqdm(lbs)
    for lb_arn in pbar:
        if not dry_run and "populated_target_groups" not in lbs[lb_arn]:
            try:
                lb_attributes = elb_client.describe_load_balancer_attributes(
                    LoadBalancerArn=lb_arn
                )["Attributes"]

                if any(
                    attr["Key"] == "deletion_protection.enabled"
                    and attr["Value"] == "true"
                    for attr in lb_attributes
                ):
                    pbar.write(
                        f"Load balancer {lb_arn} has deletion protection enabled, disabling..."
                    )
                    disable_lb_deletion_protection(elb_client, lb_arn)

                del_result = elb_client.delete_load_balancer(LoadBalancerArn=lb_arn)

                if del_result["ResponseMetadata"]["HTTPStatusCode"] != 200:
                    pbar.write(f"Failed to delete load balancer {lb_arn}: {del_result}")

            except Exception as e:
                pbar.write(f"Failed to delete load balancer {lb_arn} with error {e}")

            pbar.write(f"waiting for load balancer {lb_arn} to be deleted...")
            waiter.wait(
                LoadBalancerArns=[lb_arn],
                WaiterConfig={"Delay": 15, "MaxAttempts": 100},
            )
            sleep(5)
        pbar.write(f"deleted load balancer {lb_arn} (dry run: {dry_run})")

        delete_tgs(session, lbs[lb_arn]["empty_target_groups"])

    return None


def delete_ebs_volumes(volume_ids, session, dry_run=False):
    ec2 = session.resource("ec2")
    for volume_id in volume_ids:
        volume = ec2.Volume(volume_id)
        print("Deleting volume {}".format(volume_id))
        if not dry_run:
            volume.delete()


def estimate_snapshots_cost(session, snapshot_ids):
    ec2 = session.client("ec2")

    # Pricing details (as of September 2021)
    # This value might change, so you should update it based on the current pricing details
    price_per_gb_month = 0.05

    total_size_gb = 0
    for snapshot_id in snapshot_ids:
        snapshot = ec2.describe_snapshots(SnapshotIds=[snapshot_id])["Snapshots"][0]
        total_size_gb += snapshot["VolumeSize"]

    cost = total_size_gb * price_per_gb_month

    return cost


def delete_ebs_snapshots(snapshot_ids, session, dry_run=False):
    ec2 = session.client("ec2")
    for snapshot_id in snapshot_ids:
        print("Deleting snapshot {}".format(snapshot_id))
        if not dry_run:
            ec2.delete_snapshot(SnapshotId=snapshot_id)


def get_old_snapshots(session, days):
    ec2 = session.client("ec2")

    now = datetime.now()
    snapshots = ec2.describe_snapshots(OwnerIds=["self"])["Snapshots"]
    old_snapshots = [
        snapshot["SnapshotId"]
        for snapshot in snapshots
        if (now - snapshot["StartTime"].replace(tzinfo=None)) > timedelta(days=days)
    ]

    return old_snapshots


def scan_for_tgs_no_targets_or_lb(session):
    elb_client = session.client("elbv2")

    unused_target_groups = {
        tg["TargetGroupArn"]: {
            "TargetHealthDescriptions": elb_client.describe_target_health(
                TargetGroupArn=tg["TargetGroupArn"]
            )["TargetHealthDescriptions"],
            "LoadBalancerArns": tg["LoadBalancerArns"],
        }
        for tg in elb_client.describe_target_groups()["TargetGroups"]
    }

    tgs = []

    print("getting target groups with zero targets or no configured load balancer...")
    for target_group_arn in tqdm(unused_target_groups):
        sleep(0.05)

        if len(unused_target_groups[target_group_arn]["TargetHealthDescriptions"]) == 0:
            tgs.append(target_group_arn)

        if len(unused_target_groups[target_group_arn]["LoadBalancerArns"]) == 0:
            tgs.append(target_group_arn)

    return tgs


def scan_for_lbs_no_targets(session, region, omit_pricing=False):
    elb_client = session.client("elbv2")

    print("getting hourly costs of load balancers...")

    if not omit_pricing:
        hourly_costs = get_lb_hourly_costs(session)

    response = elb_client.describe_load_balancers()

    if len(response["LoadBalancers"]) == 0:
        print(f"No load balancers found in region {region}")
        return {"total_monthly_cost": 0}

    lbs = {}

    for lb in tqdm(response["LoadBalancers"]):
        lb_arn = lb["LoadBalancerArn"]

        if not omit_pricing:
            lb_cost_value = (
                float(list(hourly_costs[lb["Type"]][region].values())[0]) * 730
            )
        else:
            lb_cost_value = 0

        lb_target_groups = {
            tg["TargetGroupArn"]: elb_client.describe_target_health(
                TargetGroupArn=tg["TargetGroupArn"]
            )
            for tg in elb_client.describe_target_groups(LoadBalancerArn=lb_arn)[
                "TargetGroups"
            ]
        }

        for lb_target_group_arn in lb_target_groups:
            if (
                len(lb_target_groups[lb_target_group_arn]["TargetHealthDescriptions"])
                == 0
            ):
                if lb_arn not in lbs:
                    lbs[lb_arn] = {
                        "monthly_cost": lb_cost_value,
                        "empty_target_groups": [lb_target_group_arn],
                    }
                else:
                    lbs[lb_arn]["empty_target_groups"].append(lb_target_group_arn)

        if lb_arn in lbs:
            for lb_target_group_arn in lb_target_groups:
                if (
                    len(
                        lb_target_groups[lb_target_group_arn][
                            "TargetHealthDescriptions"
                        ]
                    )
                    != 0
                ):
                    if "populated_target_groups" not in lbs[lb_arn]:
                        lbs[lb_arn]["populated_target_groups"] = [lb_target_group_arn]
                    else:
                        lbs[lb_arn]["populated_target_groups"].append(
                            lb_target_group_arn
                        )

    lbs["total_monthly_cost"] = sum([lbs[lb]["monthly_cost"] for lb in lbs])

    return lbs


def scan_for_unused_ebs_volumes(session):
    client = session.client("ec2")

    cost_per_gb_map = {
        "gp3": 0.08,
        "gp2": 0.1,
        "io1": 0.125,
        "io2": 0.125,
        "st1": 0.045,
        "sc1": 0.025,
        "standard": 0.05,
    }

    volumes = client.describe_volumes()["Volumes"]

    print("getting unused ebs volumes...")
    unused_volumes = {
        "volumes": [
            {
                "VolumeId": volume["VolumeId"],
                "Size": volume["Size"],
                "CreateTime": str(volume["CreateTime"]),
                "MultiAttachEnabled": volume["MultiAttachEnabled"],
                "Attachments": volume["Attachments"],
                "MonthlyCost": volume["Size"] * cost_per_gb_map[volume["VolumeType"]],
            }
            for volume in tqdm(volumes)
            if volume["State"] == "available"
        ]
    }

    unused_volumes["total_monthly_cost"] = sum(
        [volume["MonthlyCost"] for volume in unused_volumes["volumes"]]
    )

    return unused_volumes
