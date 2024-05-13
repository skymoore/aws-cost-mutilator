from .ec2 import delete_tgs, delete_lbs, disable_lb_deletion_protection
from .ec2 import (
    scan_for_tgs_no_targets_or_lb,
    scan_for_lbs_no_targets,
    delete_ebs_volumes,
)
from .s3 import get_buckets, get_bucket_cost
import boto3
from moto import mock_elbv2, mock_ec2, mock_s3


# Create a mock Elastic Load Balancing client
@mock_elbv2
def test_delete_tgs():
    # Create a mock Elastic Load Balancing client
    elb_client = boto3.client("elbv2")

    # Define the expected response of the mock describe_target_groups method
    expected_response = {"TargetGroups": []}

    # Create a mock describe_target_groups method that returns the expected response
    elb_client.describe_target_groups = lambda **kwargs: expected_response

    # Test deleting target groups
    session = boto3.Session(region_name="us-west-2", profile_name="default")
    tgs = ["tg-1234567890", "tg-0987654321"]
    dry_run = False
    delete_tgs(session, tgs, dry_run)

    # Verify that the target groups were deleted
    response = elb_client.describe_target_groups()
    assert response == expected_response

    # Test dry run deleting target groups
    session = boto3.Session(region_name="us-west-2", profile_name="default")
    tgs = ["tg-1234567890", "tg-0987654321"]
    dry_run = True
    delete_tgs(session, tgs, dry_run)

    # Verify that the target groups were not deleted
    response = elb_client.describe_target_groups(TargetGroupArns=tgs)
    assert response == expected_response


@mock_ec2
@mock_elbv2
def test_delete_lbs():
    # Create a mock AWS session
    session = boto3.Session(
        region_name="us-east-1",
        aws_access_key_id="mock_access_key",
        aws_secret_access_key="mock_secret_key",
    )

    # Create a mock VPC and a mock subnet
    ec2_client = session.client("ec2")
    vpc_id = ec2_client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet_id = ec2_client.create_subnet(
        VpcId=vpc_id,
        CidrBlock="10.0.0.0/24",
    )[
        "Subnet"
    ]["SubnetId"]

    # Create a mock Elastic Load Balancer
    elb_client = session.client("elbv2")
    elb_response = elb_client.create_load_balancer(
        Name="mock-elb",
        Subnets=[subnet_id],
        SecurityGroups=["sg-12345678"],
    )
    elb_arn = elb_response["LoadBalancers"][0]["LoadBalancerArn"]

    # Create a mock target group
    tg_response = elb_client.create_target_group(
        Name="mock-tg",
        Protocol="HTTP",
        Port=80,
        VpcId=vpc_id,
    )
    tg_arn = tg_response["TargetGroups"][0]["TargetGroupArn"]

    # Add the target group to the load balancer
    elb_client.create_listener(
        LoadBalancerArn=elb_arn,
        Protocol="HTTP",
        Port=80,
        DefaultActions=[
            {
                "Type": "forward",
                "TargetGroupArn": tg_arn,
            },
        ],
    )

    # Create the input argument for the delete_lbs function
    lbs = {
        elb_arn: {
            "empty_target_groups": [tg_arn],
        }
    }

    # Test the delete_lbs function with dry_run=True
    delete_lbs(session, lbs, dry_run=True)

    # Verify that the load balancer and target group were not deleted
    elb_response = elb_client.describe_load_balancers()
    assert len(elb_response["LoadBalancers"]) == 1

    tg_response = elb_client.describe_target_groups()
    assert len(tg_response["TargetGroups"]) == 1

    # Test the delete_lbs function with dry_run=False
    delete_lbs(session, lbs)

    # Verify that the load balancer and target group were deleted
    elb_response = elb_client.describe_load_balancers()
    assert len(elb_response["LoadBalancers"]) == 0

    tg_response = elb_client.describe_target_groups()
    assert len(tg_response["TargetGroups"]) == 0


@mock_ec2
@mock_elbv2
def test_disable_lb_deletion_protection():
    # Create a mock AWS session
    session = boto3.Session(
        region_name="us-east-1",
        aws_access_key_id="mock_access_key",
        aws_secret_access_key="mock_secret_key",
    )

    # Create a mock VPC and a mock subnet
    ec2_client = session.client("ec2")
    vpc_id = ec2_client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet_id = ec2_client.create_subnet(
        VpcId=vpc_id,
        CidrBlock="10.0.0.0/24",
    )[
        "Subnet"
    ]["SubnetId"]

    # Create a mock Elastic Load Balancer
    elb_client = session.client("elbv2")
    elb_response = elb_client.create_load_balancer(
        Name="mock-elb",
        Subnets=[subnet_id],
        SecurityGroups=["sg-12345678"],
    )
    elb_arn = elb_response["LoadBalancers"][0]["LoadBalancerArn"]

    # Enable deletion protection for the load balancer
    elb_client.modify_load_balancer_attributes(
        LoadBalancerArn=elb_arn,
        Attributes=[{"Key": "deletion_protection.enabled", "Value": "true"}],
    )

    # Call the disable_lb_deletion_protection function
    disable_lb_deletion_protection(elb_client, elb_arn)

    # Verify that deletion protection has been disabled
    elb_response = elb_client.describe_load_balancer_attributes(LoadBalancerArn=elb_arn)
    attributes = elb_response["Attributes"]
    assert any(
        attr["Key"] == "deletion_protection.enabled" and attr["Value"] == "false"
        for attr in attributes
    )


@mock_ec2
@mock_elbv2
def test_scan_for_tgs_no_targets_or_lb():
    # Create a mock AWS session
    session = boto3.Session(
        region_name="us-east-1",
        aws_access_key_id="mock_access_key",
        aws_secret_access_key="mock_secret_key",
    )

    # Create a mock VPC and a mock subnet
    ec2_client = session.client("ec2")
    vpc_id = ec2_client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet_id = ec2_client.create_subnet(
        VpcId=vpc_id,
        CidrBlock="10.0.0.0/24",
    )[
        "Subnet"
    ]["SubnetId"]

    # Create a mock Elastic Load Balancer
    elb_client = session.client("elbv2")
    elb_response = elb_client.create_load_balancer(
        Name="mock-elb",
        Subnets=[subnet_id],
        SecurityGroups=["sg-12345678"],
    )
    elb_arn = elb_response["LoadBalancers"][0]["LoadBalancerArn"]

    # Create a mock target group
    tg_response = elb_client.create_target_group(
        Name="mock-tg",
        Protocol="HTTP",
        Port=80,
        VpcId=vpc_id,
    )
    tg_arn = tg_response["TargetGroups"][0]["TargetGroupArn"]

    # Add the target group to the load balancer
    listener_arn = elb_client.create_listener(
        LoadBalancerArn=elb_arn,
        Protocol="HTTP",
        Port=80,
        DefaultActions=[
            {
                "Type": "forward",
                "TargetGroupArn": tg_arn,
            },
        ],
    )["Listeners"][0]["ListenerArn"]

    # Call the get_tgs_no_targets_or_lb function
    target_groups = scan_for_tgs_no_targets_or_lb(session)

    # Verify that the target group is returned by the function
    assert tg_arn in target_groups

    ami_id = ec2_client.describe_images()["Images"][0]["ImageId"]

    # Create a mock EC2 instance
    ec2_response = ec2_client.run_instances(
        ImageId=ami_id,
        InstanceType="t2.micro",
        MaxCount=1,
        MinCount=1,
        NetworkInterfaces=[
            {
                "SubnetId": subnet_id,
                "DeviceIndex": 0,
                "AssociatePublicIpAddress": True,
            },
        ],
    )

    # Get Instance Id
    instance_id = ec2_response["Instances"][0]["InstanceId"]

    # Add a target to the target group
    elb_client.register_targets(
        TargetGroupArn=tg_arn,
        Targets=[
            {
                "Id": instance_id,
                "Port": 80,
            },
        ],
    )

    # Call the get_tgs_no_targets_or_lb function
    target_groups = scan_for_tgs_no_targets_or_lb(session)

    # Verify that the target group is not returned by the function
    assert tg_arn not in target_groups

    # Remove the load balancer from the target group
    elb_client.delete_listener(
        ListenerArn=listener_arn,
    )
    elb_client.deregister_targets(
        TargetGroupArn=tg_arn,
        Targets=[
            {
                "Id": instance_id,
                "Port": 80,
            },
        ],
    )

    # Call the get_tgs_no_targets_or_lb function
    target_groups = scan_for_tgs_no_targets_or_lb(session)

    # Verify that the target group is returned by the function
    assert tg_arn in target_groups


@mock_ec2
@mock_elbv2
def test_scan_for_lbs_no_targets():
    region = "us-east-1"
    # Create a mock AWS session
    session = boto3.Session(
        region_name="us-east-1",
        aws_access_key_id="mock_access_key",
        aws_secret_access_key="mock_secret_key",
    )

    # Create a mock VPC and a mock subnet
    ec2_client = session.client("ec2")
    vpc_id = ec2_client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet_id = ec2_client.create_subnet(
        VpcId=vpc_id,
        CidrBlock="10.0.0.0/24",
    )[
        "Subnet"
    ]["SubnetId"]

    # Create a mock Elastic Load Balancer
    elb_client = session.client("elbv2")
    elb_response = elb_client.create_load_balancer(
        Name="mock-elb",
        Subnets=[subnet_id],
        SecurityGroups=["sg-12345678"],
    )
    elb_arn = elb_response["LoadBalancers"][0]["LoadBalancerArn"]

    # Create a mock target group
    tg_response = elb_client.create_target_group(
        Name="mock-tg",
        Protocol="HTTP",
        Port=80,
        VpcId=vpc_id,
    )
    tg_arn = tg_response["TargetGroups"][0]["TargetGroupArn"]

    # Add the target group to the load balancer
    elb_client.create_listener(
        LoadBalancerArn=elb_arn,
        Protocol="HTTP",
        Port=80,
        DefaultActions=[
            {
                "Type": "forward",
                "TargetGroupArn": tg_arn,
            },
        ],
    )["Listeners"][0]["ListenerArn"]

    # Call the get_lbs_no_targets function
    load_balancers = scan_for_lbs_no_targets(session, region, omit_pricing=True)

    assert elb_arn in load_balancers


@mock_ec2
def test_scan_for_unused_ebs_volumes():
    session = boto3.Session(region_name="us-east-1")
    client = session.client("ec2")

    # Create an EBS volume
    client.create_volume(AvailabilityZone="us-east-1a", Size=1, VolumeType="gp2")

    # Get the list of all EBS volumes in the region
    volumes = client.describe_volumes()["Volumes"]

    # Filter the list to include only volumes that are not attached to any EC2 instances
    unused_volumes = [volume for volume in volumes if volume["State"] == "available"]

    # Assert that the list is not empty
    assert len(unused_volumes) > 0

    # Assert that the list contains the EBS volume that we created
    assert len([volume for volume in unused_volumes if volume["Size"] == 1]) == 1


@mock_ec2
def test_delete_ebs_volumes():
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.resource("ec2")

    # create a volume to delete
    volume = ec2.create_volume(AvailabilityZone="us-east-1a", Size=10)

    # delete the volume and confirm it is deleted
    assert delete_ebs_volumes([volume.id], session) is None
    assert list(ec2.volumes.all()) == []


@mock_s3
def test_get_old_buckets():
    # Create a boto3 session for testing
    session = boto3.Session(region_name="us-east-1")

    # Create a client for the S3 service
    s3 = session.client("s3")

    # Create a test bucket
    s3.create_bucket(Bucket="test-bucket")

    # Check that the function correctly identifies an empty bucket as old
    buckets = get_buckets(session, 365)
    assert "test-bucket" in buckets["empty"]

    # Add a new object to the test bucket
    s3.put_object(Bucket="test-bucket", Key="test.txt", Body=b"test")

    # Check that the function does not consider the bucket to be old
    buckets = get_buckets(session, 365)
    assert "test-bucket" not in buckets["old"]


@mock_s3
def test_get_bucket_cost():
    # Create a boto3 session for testing
    session = boto3.Session(region_name="us-east-1")

    # Create a client for the S3 service
    s3 = session.client("s3")

    # Create a test bucket
    s3.create_bucket(Bucket="test-bucket")

    # Check that the cost of an empty bucket is 0
    cost = get_bucket_cost(session, "test-bucket")
    assert cost == 0

    # Add an object to the test bucket
    s3.put_object(Bucket="test-bucket", Key="test.txt", Body=b"0123456789")

    # Check that the cost of the bucket is calculated correctly
    cost = get_bucket_cost(session, "test-bucket")
    assert cost > 0
