from datetime import datetime, timedelta, UTC
from tqdm import tqdm


def get_buckets(session, days):
    cutoff_time = datetime.now(UTC) - timedelta(days=days)

    s3 = session.client("s3")

    s3_buckets = {"old": [], "empty": []}

    response = s3.list_buckets()
    buckets = response["Buckets"]

    pbar = tqdm(buckets)
    for bucket in pbar:
        bucket_name = bucket["Name"]

        response = s3.list_objects_v2(Bucket=bucket_name)
        if "Contents" not in response:
            s3_buckets["empty"].append(bucket_name)
            continue

        newest_object = response["Contents"][0]
        newest_object_time = newest_object["LastModified"]

        if newest_object_time < cutoff_time:
            s3_buckets["old"].append(bucket_name)

    return s3_buckets


def get_bucket_cost(session, bucket_name):
    s3 = session.client("s3")

    size = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name):
        if "Contents" not in page:
            # bucket is empty
            continue

        for obj in page["Contents"]:
            size += obj["Size"]

    # Calculate the cost based on the size of the data
    # (Assumes the standard S3 pricing model with a cost of $0.023 per GB per month)
    cost = (size / 1024**3) * 0.023

    return cost
