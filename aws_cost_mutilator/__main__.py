from boto3 import Session
from click import group, option, pass_context

import json
from .ec2 import (
    scan_for_lbs_no_targets,
    delete_lbs,
    scan_for_tgs_no_targets_or_lb,
    delete_tgs,
    scan_for_unused_ebs_volumes,
    delete_ebs_volumes,
    get_old_snapshots,
    estimate_snapshots_cost,
)
from .s3 import get_buckets, get_bucket_cost
from .iam import get_unused_iam_roles


@group()
@option("--profile", "-p", required=False, help="AWS profile")
@option("--region", "-r", required=False, help="AWS region")
@pass_context
def cli(ctx, profile, region):
    print("Welcome to the AWS Cost Mutilator!")
    ctx.obj = {}

    if profile and region:
        ctx.obj["session"] = Session(region_name=region, profile_name=profile)
        ctx.obj["profile"] = profile
        ctx.obj["region"] = region
    elif profile:
        ctx.obj["session"] = Session(profile_name=profile)
        ctx.obj["profile"] = profile
        ctx.obj["region"] = ctx.obj["session"].region_name
    elif region:
        ctx.obj["session"] = Session(region_name=region)
        ctx.obj["profile"] = ctx.obj["session"].profile_name
        ctx.obj["region"] = region
    else:
        ctx.obj["session"] = Session()
        ctx.obj["profile"] = ctx.obj["session"].profile_name
        ctx.obj["region"] = ctx.obj["session"].region_name


@cli.group()
@pass_context
def check(ctx):
    pass


@cli.group()
@option("--dry-run", "-d", is_flag=True, help="Perform a dry run")
@pass_context
def clean(ctx, dry_run):
    ctx.obj["dry_run"] = dry_run
    pass


@check.command("s3")
@option(
    "--days",
    type=int,
    default=365,
    help="Find empty buckets and buckets with no objects newer than this number of days",
)
@pass_context
def s3_(ctx, days):
    session = ctx.obj["session"]
    profile = ctx.obj["profile"]
    buckets = get_buckets(session, days)
    cost = 0
    for bucket_name in buckets["old"]:
        cost += get_bucket_cost(session, bucket_name)
    print(json.dumps(buckets, indent=4))
    print(
        f"Run:\n\nacm --profile {profile} clean s3 --days {days}\n\nto delete these resources and save ${cost:.2f} per month"
    )


@check.command("roles")
@option("--days", type=int, help="Find roles unused for this many days")
@pass_context
def roles_(ctx, days):
    session = ctx.obj["session"]
    unused_roles = get_unused_iam_roles(session, days)

    if len(unused_roles) == 0:
        print("No unused IAM roles found!")
        exit(0)

    print(
        f"There are {len(unused_roles)} IAM roles unused for more than {days} {'day' if days == 1 else 'days'}:"
    )
    print(json.dumps(unused_roles, indent=4))


@check.command("ebs")
@pass_context
def ebs_(ctx):
    session = ctx.obj["session"]
    region = ctx.obj["region"]
    profile = ctx.obj["profile"]
    unused_ebs_volumes = scan_for_unused_ebs_volumes(session)
    total_monthly_cost = unused_ebs_volumes["total_monthly_cost"]
    del unused_ebs_volumes["total_monthly_cost"]

    if len(unused_ebs_volumes) == 0:
        print("No unused EBS volumes found!")
        return

    print(f"There are {len(unused_ebs_volumes['volumes'])} unused EBS volumes:")
    print(json.dumps(unused_ebs_volumes["volumes"], indent=4))
    print(
        f"Run:\n\nacm clean ebs --region {region} --profile {profile}\n\nto delete these resources and save ${total_monthly_cost:.2f} per month"
    )
    exit(0)


@check.command("ebssnap")
@option("--older-than", type=int, help="Find snapshots older than this many days")
@pass_context
def ebs_snapshots_(ctx, older_than):
    session = ctx.obj["session"]
    region = ctx.obj["region"]
    profile = ctx.obj["profile"]
    old_snapshots = get_old_snapshots(session, older_than)

    if len(old_snapshots) == 0:
        print("No old EBS snapshots found!")
        exit(0)

    else:
        total_monthly_cost = estimate_snapshots_cost(session, old_snapshots)

    print(
        f"There are {len(old_snapshots)} EBS snapshots older than {older_than} {'day' if older_than == 1 else 'days'}:"
    )
    print(json.dumps(old_snapshots, indent=4))
    print(
        f"Run:\n\nacm clean ebsnap --region {region} --profile {profile} --older-than {older_than}\n\nto delete these resources and save ${total_monthly_cost:.2f} per month"
    )
    exit(0)


@check.command("tgs")
@pass_context
def tgs_(ctx):
    session = ctx.obj["session"]
    target_groups = scan_for_tgs_no_targets_or_lb(session)

    if len(target_groups) == 0:
        print("No target groups without targets or load balancers found!")
        return

    print(
        f"There are {len(target_groups)} target groups with zero targets or no load balancer:"
    )
    print(json.dumps(target_groups, indent=4))


@check.command("lbs")
@pass_context
def lbs_(ctx):
    # Perform analysis of ELBv2 resources in the specified region and profile
    session = ctx.obj["session"]
    region = ctx.obj["region"]
    profile = ctx.obj["profile"]
    load_balancers = scan_for_lbs_no_targets(session, region, region)

    total_monthly_cost = load_balancers["total_monthly_cost"]
    del load_balancers["total_monthly_cost"]
    num_lbs_no_targets = len(load_balancers)

    if num_lbs_no_targets == 0:
        print("No load balancers without targets found!")
        return

    print(f"There are {len(load_balancers)} load balancers with empty target groups:")
    print(json.dumps(load_balancers, indent=4))
    print(
        f"Run:\n\nacm clean elbv2 --region {region} --profile {profile}\n\nto delete these resources and save ${total_monthly_cost:.2f} per month"
    )

    exit(0)


# CLEAN COMMANDS


@clean.command("s3")
@option(
    "--days",
    type=int,
    default=365,
    help="Delete empty buckets and buckets with no objects newer than this number of days",
)
@pass_context
def s3(ctx, days):
    raise NotImplementedError("This feature is not yet implemented")


@clean.command("tgs")
@pass_context
def tgs(ctx):
    session = ctx.obj["session"]
    dry_run = ctx.obj["dry_run"]
    target_groups = scan_for_tgs_no_targets_or_lb(session)

    num_tgs = len(target_groups)

    if num_tgs == 0:
        print("No target groups without targets or load balancers found!")
        return

    print(
        f"There are {len(target_groups)} target groups with zero targets or no load balancer:"
    )
    print(json.dumps(target_groups, indent=4))

    # Ask the user for confirmation
    response = input(
        f"Are you sure you want to continue? This will delete {num_tgs} target groups. (yes/no): "
    )

    # Check the user's response
    if response == "yes":
        # Execute the code if the response was "yes"
        if dry_run:
            print("Dry run mode enabled, no resources will be deleted.")

        delete_tgs(session, target_groups, dry_run)

        print(f"Deleted {num_tgs} target groups.")
        # print(
        #     f"Deleted {num_tgs} load balancers and their associated target groups saving ${total_monthly_cost:.2f} per month."
        # )

    else:
        # Exit the program if the response was "no" or anything else
        print("Aborted")

    exit(0)


@clean.command("lbs")
@pass_context
def lbs(ctx):
    # Perform analysis of ELBv2 resources in the specified region and profile
    session = ctx.obj["session"]
    region = ctx.obj["region"]
    dry_run = ctx.obj["dry_run"]
    load_balancers = scan_for_lbs_no_targets(session, region)
    total_monthly_cost = load_balancers["total_monthly_cost"]
    del load_balancers["total_monthly_cost"]
    num_lbs = len(load_balancers)

    if num_lbs == 0:
        print("No load balancers without targets found!")
        return

    print(f"There are {num_lbs} load balancers with empty target groups:")
    print(json.dumps(load_balancers, indent=4))

    # Ask the user for confirmation
    response = input(
        f"Are you sure you want to continue? This will delete {num_lbs} load balancers and their associated target groups. If there are both populated and empty target groups associated with a load balancer, it will detach and delete only the empty target groups, leaving the load balancer and populated target groups in place. (yes/no): "
    )

    # Check the user's response
    if response == "yes":
        # Execute the code if the response was "yes"
        if dry_run:
            print("Dry run mode enabled, no resources will be deleted.")

        delete_lbs(session, load_balancers, dry_run)

        print(
            f"Deleted {num_lbs} load balancers and their associated target groups saving ${total_monthly_cost:.2f} per month."
        )

    else:
        # Exit the program if the response was "no" or anything else
        print("Aborted")

    exit(0)


@clean.command("ebs")
@pass_context
def ebs(ctx):
    session = ctx.obj["session"]
    dry_run = ctx.obj["dry_run"]
    unused_ebs_volumes = scan_for_unused_ebs_volumes(session)
    total_monthly_cost = unused_ebs_volumes["total_monthly_cost"]
    del unused_ebs_volumes["total_monthly_cost"]

    if len(unused_ebs_volumes) == 0:
        print("No unused EBS volumes found!")
        return

    print(f"There are {len(unused_ebs_volumes['volumes'])} unused EBS volumes:")
    print(json.dumps(unused_ebs_volumes["volumes"], indent=4))

    # Ask the user for confirmation
    response = input(
        f"Are you sure you want to continue? This will delete {len(unused_ebs_volumes['volumes'])} EBS volumes. (yes/no): "
    )
    if response == "yes":
        # Execute the code if the response was "yes"
        if dry_run:
            print("Dry run mode enabled, no resources will be deleted.")

        delete_ebs_volumes(
            session, [vol["VolumeId"] for vol in unused_ebs_volumes], dry_run
        )
        print(
            f"Deleted {len(unused_ebs_volumes['volumes'])} EBS volumes saving ${total_monthly_cost:.2f} per month."
        )
    else:
        # Exit the program if the response was "no" or anything else
        print("Aborted")

    exit(0)


if __name__ == "__main__":
    cli()
