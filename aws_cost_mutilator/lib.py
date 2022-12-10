import boto3, json
from tqdm import tqdm
from time import sleep


def boto_session(region, profile):
    session = boto3.Session(region_name=region, profile_name=profile)

    try:
        session.client("sts").get_caller_identity()
        return session

    except Exception as e:
        print(f"Error: {e}")
        exit(1)


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


def delete_tgs(session, region, profile, tgs, dry_run=False):
    # Create an AWS client for the Elastic Load Balancing service
    elb_client = session.client("elbv2")

    print(f"deleting elbv2 resources with profile {profile} in region {region}...")

    pbar = tqdm(tgs)
    for tg_arn in pbar:
        if not dry_run:
            try:
                elb_client.delete_target_group(TargetGroupArn=tg_arn)
            except Exception as e:
                pbar.write(f"Failed to delete target group {tg_arn} with error {e}")
        pbar.write(f"deleted target group {tg_arn} (dry run: {dry_run})")

    return None


def delete_lbs(session, region, profile, lbs, dry_run=False):
    # Create an AWS client for the Elastic Load Balancing service
    elb_client = session.client("elbv2")
    waiter = elb_client.get_waiter("load_balancers_deleted")

    print(f"deleting elbv2 resources with profile {profile} in region {region}...")

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
                    elb_client.modify_load_balancer_attributes(
                        LoadBalancerArn=lb_arn,
                        Attributes=[
                            {"Key": "deletion_protection.enabled", "Value": "false"}
                        ],
                    )

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
        for target_group_arn in lbs[lb_arn]["empty_target_groups"]:
            if not dry_run:
                # elb_client.detach_target_groups(TargetGroupArn=target_group_arn, LoadBalancerArn=lb_arn)
                try:
                    elb_client.delete_target_group(TargetGroupArn=target_group_arn)
                except Exception as e:
                    pbar.write(
                        f"Failed to delete target group {target_group_arn} with error {e}"
                    )
            pbar.write(f"deleted target group {target_group_arn} (dry run: {dry_run})")

    return None


def get_tgs_no_targets_or_lb(session, region, profile):
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


def get_lbs_no_targets(session, region, profile):
    # Create an AWS client for the Elastic Load Balancing service
    elb_client = session.client("elbv2")

    # Get the hourly costs of the load balancers
    print("getting hourly costs of load balancers...")
    hourly_costs = get_lb_hourly_costs(session)

    # Get the list of load balancers in the specified region
    response = elb_client.describe_load_balancers()

    if len(response["LoadBalancers"]) == 0:
        print(f"No load balancers found in region {region}")
        return {"total_monthly_cost": 0}

    # List to store the ARNs of load balancers with no targets
    lbs = {}

    print(f"analyzing elbv2 resources with profile {profile} in region {region}...")

    # Iterate over the load balancers
    for lb in tqdm(response["LoadBalancers"]):
        # Get the ARN of the load balancer
        lb_arn = lb["LoadBalancerArn"]

        # Get the monthly cost of the load balancer
        lb_cost_value = float(list(hourly_costs[lb["Type"]][region].values())[0]) * 730

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
