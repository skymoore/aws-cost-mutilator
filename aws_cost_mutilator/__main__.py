import click
import json
from .lib import (
    get_lbs_no_targets,
    delete_lbs,
    boto_session,
    get_tgs_no_targets_or_lb,
    delete_tgs,
)


@click.group()
def cli():
    print("Welcome to the AWS Cost Mutilator!")
    pass


@cli.group()
@click.option("--region", help="The AWS region to use")
@click.option("--profile", help="The AWS profile to use")
def check(region, profile):
    pass


@check.command()
@click.option("--region", help="The AWS region to use")
@click.option("--profile", help="The AWS profile to use")
def tgs_(region, profile):
    session = boto_session(region, profile)
    target_groups = get_tgs_no_targets_or_lb(session)

    if len(target_groups) == 0:
        print("No target groups without targets or load balancers found!")
        return

    print(
        f"There are {len(target_groups)} target groups with zero targets or no load balancer:"
    )
    print(json.dumps(target_groups, indent=4))


@check.command()
@click.option("--region", help="The AWS region to use")
@click.option("--profile", help="The AWS profile to use")
def lbs_(region, profile):
    # Perform analysis of ELBv2 resources in the specified region and profile
    session = boto_session(region, profile)
    load_balancers = get_lbs_no_targets(session)

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


@cli.group()
@click.option("--region", help="The AWS region to use")
@click.option("--profile", help="The AWS profile to use")
@click.option("--dry-run", is_flag=True, help="Perform a dry run")
def clean(region, profile, dry_run):
    pass


@clean.command()
@click.option("--region", help="The AWS region to use")
@click.option("--profile", help="The AWS profile to use")
@click.option("--dry-run", is_flag=True, help="Perform a dry run")
def tgs(region, profile, dry_run):
    session = boto_session(region, profile)
    target_groups = get_tgs_no_targets_or_lb(session)

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


@clean.command()
@click.option("--region", help="The AWS region to use")
@click.option("--profile", help="The AWS profile to use")
@click.option("--dry-run", is_flag=True, help="Perform a dry run")
def lbs(region, profile, dry_run):
    # Perform analysis of ELBv2 resources in the specified region and profile
    session = boto_session(region, profile)
    load_balancers = get_lbs_no_targets(session, region)
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


if __name__ == "__main__":
    cli()
