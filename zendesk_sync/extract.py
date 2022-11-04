import gzip
import json
import os
import pathlib
import traceback
from datetime import datetime, timedelta, timezone

from google.cloud import storage
from zenpy import Zenpy

from datarobot.utilities import email

SCRIPT_DIR = pathlib.Path(__file__).absolute().parent


def to_json(data, file_name):
    file_path = SCRIPT_DIR / "data" / file_name
    if not file_path.parent.exists():
        file_path.parent.mkdir(parents=True)

    with gzip.open(file_path, "wt", encoding="utf-8") as f:
        json.dump(data, f)

    return file_path


def upload_to_gcs(bucket, schema, file_path):
    parts = file_path.parts
    blob = bucket.blob(f"{schema}/{'/'.join(parts[parts.index('data') + 1:])}")
    blob.upload_from_filename(file_path)
    return blob


def main():
    today = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    query_date = today - timedelta(days=3)

    zenpy_client = Zenpy(
        email=os.getenv("ZENDESK_EMAIL"),
        token=os.getenv("ZENDESK_TOKEN"),
        subdomain=os.getenv("ZENDESK_SUBDOMAIN"),
    )

    gcs_storage_client = storage.Client()
    gcs_bucket = gcs_storage_client.bucket(os.getenv("GCS_BUCKET_NAME"))

    endpoint = "ticket_metrics"
    file_dir = SCRIPT_DIR / "data" / endpoint
    if not file_dir.exists():
        file_dir.mkdir(parents=True)
        print(f"Created {file_dir}...")

        # archived ticket metrics
        print("Downloading metrics for archived tickets...")
        tm_ids = [tm.ticket_id for tm in zenpy_client.ticket_metrics()]
        archive_ticket_ids = [i for i in range(max(tm_ids)) if i not in tm_ids]

        archive_data = [
            zenpy_client.tickets.metrics(ati).to_dict() for ati in archive_ticket_ids
        ]

        # save file
        file_name = f"{endpoint}/archive.json.gz"
        archive_file_path = to_json(archive_data, file_name)
        print(f"\tSaved to {archive_file_path}!")

        # push to GCS
        blob = upload_to_gcs(gcs_bucket, "zendesk", archive_file_path)
        print(f"\tUploaded to {blob.public_url}!")

    # current data at ticket_metrics endpoint
    print("Downloading all current ticket metrics...")
    all_data = [tm.to_dict() for tm in zenpy_client.ticket_metrics()]
    filtered_data = [
        d
        for d in all_data
        if datetime.fromisoformat(d["updated_at"].replace("Z", "+00:00")) >= query_date
    ]

    # save file
    file_name = f"{endpoint}/{str(query_date.timestamp()).replace('.', '_')}.json.gz"
    file_path = to_json(filtered_data, file_name)
    print(f"\tSaved to {file_path}!")

    # push to GCS
    blob = upload_to_gcs(gcs_bucket, "zendesk", file_path)
    print(f"\tUploaded to {blob.public_url}!")


if __name__ == "__main__":
    try:
        main()
    except Exception as xc:
        print(xc)
        print(traceback.format_exc())
        email_subject = "Zendesk Extract Error"
        email_body = f"{xc}\n\n{traceback.format_exc()}"
        email.send_email(subject=email_subject, body=email_body)
