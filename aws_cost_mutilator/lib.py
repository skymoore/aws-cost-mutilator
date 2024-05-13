import boto3
import json
from tqdm import tqdm
from time import sleep
from datetime import datetime, timedelta, timezone


def boto_session(region, profile):
    session = boto3.Session(region_name=region, profile_name=profile)
    session.client("sts").get_caller_identity()
    return session


def get_lb_hourly_costs(session):
    # Set up AWS client
    client = session.client("pricing", region_name="us-east-1")

    # Set up the parameters for the API call
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

    # Make the API call to get the pricing information
    net_response = client.get_products(**net_params)
    app_response = client.get_products(**app_params)
    # classic_response = client.get_products(**classic_params)

    # Create a dictionary to store the hourly costs
    hourly_costs = {"network": {}, "application": {}}  # , "classic": {}}
    responses = {
        "network": net_response,
        "application": app_response,
    }  # , "classic": classic_response}

    for response in responses:
        for product in responses[response]["PriceList"]:
            # Parse the JSON data
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
                # not worried about data costs because these are not in active use
                continue

            # Get the region and hourly cost
            region = data["product"]["attributes"]["regionCode"]
            ppu = data["terms"]["OnDemand"][product_key]["priceDimensions"][
                price_dimensions_key
            ]["pricePerUnit"]

            if region not in hourly_costs[response]:
                # Add the cost to the dictionary
                hourly_costs[response][region] = ppu

    return hourly_costs


def delete_tgs(session, tgs, dry_run=False):
    # Create an AWS client for the Elastic Load Balancing service
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
    # Create an AWS client for the Elastic Load Balancing service
    elb_client = session.client("elbv2")
    waiter = elb_client.get_waiter("load_balancers_deleted")

    pbar = tqdm(lbs)
    for lb_arn in pbar:
        if not dry_run and "populated_target_groups" not in lbs[lb_arn]:
            # Delete the load balancer
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

        # Delete the target groups
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

    # Get the size of each snapshot
    total_size_gb = 0
    for snapshot_id in snapshot_ids:
        snapshot = ec2.describe_snapshots(SnapshotIds=[snapshot_id])["Snapshots"][0]
        total_size_gb += snapshot["VolumeSize"]

    # Calculate the estimated cost
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

    # Get the current time
    now = datetime.now()

    # Get all snapshots
    snapshots = ec2.describe_snapshots(OwnerIds=["self"])["Snapshots"]

    # Filter out snapshots that are more than 'days' old
    old_snapshots = [
        snapshot["SnapshotId"]
        for snapshot in snapshots
        if (now - snapshot["StartTime"].replace(tzinfo=None)) > timedelta(days=days)
    ]

    return old_snapshots


def get_bucket_cost(session, bucket_name):
    # Get the S3 client
    s3 = session.client("s3")

    # Get the size of all of the objects in the bucket
    size = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name):
        for obj in page["Contents"]:
            size += obj["Size"]

    # Calculate the cost based on the size of the data
    # (Assumes the standard S3 pricing model with a cost of $0.023 per GB per month)
    cost = size / 1024**3 * 0.023

    return cost


def get_unused_iam_roles(session, days):
    iam = session.client("iam")
    cloudtrail = session.client("cloudtrail")
    unused_roles = []

    paginator = iam.get_paginator("list_roles")
    for response in paginator.paginate():
        for role in response["Roles"]:
            if role["RoleName"] == "cryptoassets-solana-dev-response-handler":
                pass
            if role["Path"].startswith("/aws-service-role/"):
                continue

            events = cloudtrail.lookup_events(
                LookupAttributes=[
                    {"AttributeKey": "ResourceName", "AttributeValue": role["RoleName"]}
                ],
                MaxResults=1,
            )

            # If the role has no events in CloudTrail, consider it unused
            if not events["Events"]:
                unused_roles.append(role["RoleName"])
                continue

            # Get the time of the last event
            last_event_time = events["Events"][0]["EventTime"]

            # If the last event is older than the specified number of days, consider the role unused
            if last_event_time < datetime.now(timezone.utc) - timedelta(days=days):
                unused_roles.append(role["RoleName"])

    return unused_roles


def get_old_buckets(session):
    # Get the current time and subtract one year to find the cutoff time
    cutoff_time = datetime.utcnow() - timedelta(days=365)

    # Get the S3 client
    s3 = session.client("s3")

    # Initialize an empty list to store the bucket names
    old_buckets = []

    # List all of the buckets in the account
    response = s3.list_buckets()
    buckets = response["Buckets"]

    # Iterate through the buckets
    for bucket in buckets:
        # Get the name of the bucket
        bucket_name = bucket["Name"]

        # Check if the bucket is empty
        response = s3.list_objects_v2(Bucket=bucket_name)
        if "Contents" not in response:
            # If the bucket is empty, add it to the list
            old_buckets.append(bucket_name)
            continue

        # If the bucket is not empty, check the age of the newest object
        newest_object = response["Contents"][0]
        newest_object_time = newest_object["LastModified"]

        # If the newest object is older than the cutoff time, add the bucket to the list
        if newest_object_time < cutoff_time:
            old_buckets.append(bucket_name)

    # Return the list of old buckets
    return old_buckets


def scan_for_tgs_no_targets_or_lb(session):
    # Create an elbv2 client
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
    # Print the ARN of each target group that has 0 targets or no load balancers
    for target_group_arn in tqdm(unused_target_groups):
        # sleep so progress par displays correctly
        sleep(0.05)

        if len(unused_target_groups[target_group_arn]["TargetHealthDescriptions"]) == 0:
            tgs.append(target_group_arn)

        if len(unused_target_groups[target_group_arn]["LoadBalancerArns"]) == 0:
            tgs.append(target_group_arn)

    return tgs


def scan_for_lbs_no_targets(session, region, omit_pricing=False):
    # Create an AWS client for the Elastic Load Balancing service
    elb_client = session.client("elbv2")

    # Get the hourly costs of the load balancers
    print("getting hourly costs of load balancers...")

    if not omit_pricing:
        hourly_costs = get_lb_hourly_costs(session)

    # Get the list of load balancers in the specified region
    response = elb_client.describe_load_balancers()

    if len(response["LoadBalancers"]) == 0:
        print(f"No load balancers found in region {region}")
        return {"total_monthly_cost": 0}

    # List to store the ARNs of load balancers with no targets
    lbs = {}

    # Iterate over the load balancers
    for lb in tqdm(response["LoadBalancers"]):
        # Get the ARN of the load balancer
        lb_arn = lb["LoadBalancerArn"]

        if not omit_pricing:
            # Get the monthly cost of the load balancer
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
            # If the target group has no targets
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

        # if the lb has a target group with no targets
        if lb_arn in lbs:
            # cross reference for populated target groups
            for lb_target_group_arn in lb_target_groups:
                # If the target group has targets
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
        "st1": 0.045,
        "sc1": 0.025,
        "standard": 0.05,
    }

    # Get the list of all EBS volumes in the region
    volumes = client.describe_volumes()["Volumes"]

    # Filter the list to include only volumes that are not attached to any EC2 instances
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

    # Return the list of unused EBS volumes
    return unused_volumes
