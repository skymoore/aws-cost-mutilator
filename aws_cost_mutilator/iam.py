from datetime import datetime, timedelta, timezone


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
