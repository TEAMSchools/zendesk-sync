import gzip
import json
import os
import pathlib
import traceback
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google.cloud import storage
from zenpy import Zenpy

from datarobot.utilities import email

load_dotenv()

ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_TOKEN = os.getenv("ZENDESK_TOKEN")
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

PROJECT_PATH = PROJECT_PATH = pathlib.Path(__file__).absolute().parent


def main():
    today = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    query_date = today - timedelta(days=3)

    zenpy_client = Zenpy(
        email=ZENDESK_EMAIL, token=ZENDESK_TOKEN, subdomain=ZENDESK_SUBDOMAIN
    )

    gcs_storage_client = storage.Client()
    gcs_bucket = gcs_storage_client.bucket(GCS_BUCKET_NAME)

    data_path = PROJECT_PATH / "data" / "ticket_metrics"
    if not data_path.exists():
        data_path.mkdir(parents=True)
        print(f"Created {'/'.join(data_path.parts[-3:])}...")

        # archived ticket metrics
        print("Downloading metrics for archived tickets...")
        tm_ids = [tm.ticket_id for tm in zenpy_client.ticket_metrics()]
        archive_ticket_ids = [i for i in range(max(tm_ids)) if i not in tm_ids]

        archive_data = [
            zenpy_client.tickets.metrics(ati).to_dict() for ati in archive_ticket_ids
        ]

        archive_data_filepath = data_path / "archive.json.gz"
        with gzip.open(archive_data_filepath, "wt", encoding="utf-8") as f:
            json.dump(archive_data, f)
        print(f"\tSaved to {archive_data_filepath}!")

        # push to GCS
        destination_blob_name = "zendesk/" + "/".join(archive_data_filepath.parts[-2:])
        blob = gcs_bucket.blob(destination_blob_name)
        blob.upload_from_filename(archive_data_filepath)
        print(f"\tUploaded to {destination_blob_name}!")

    # current data at ticket_metrics endpoint
    print("Downloading all current ticket metrics...")
    all_data = [tm.to_dict() for tm in zenpy_client.ticket_metrics()]
    filtered_data = [
        d
        for d in all_data
        if datetime.fromisoformat(d["updated_at"].replace("Z", "+00:00")) >= query_date
    ]

    # save file
    data_filepath = data_path / f"{query_date.isoformat()}.json.gz"
    with gzip.open(data_filepath, "wt", encoding="utf-8") as f:
        json.dump(filtered_data, f)
    print(f"\tSaved to {data_filepath}!")

    # push to GCS
    destination_blob_name = "zendesk/" + "/".join(data_filepath.parts[-2:])
    blob = gcs_bucket.blob(destination_blob_name)
    blob.upload_from_filename(data_filepath)
    print(f"\tUploaded to {destination_blob_name}!")


if __name__ == "__main__":
    try:
        main()
    except Exception as xc:
        print(xc)
        print(traceback.format_exc())
        email_subject = "Zendesk Extract Error"
        email_body = f"{xc}\n\n{traceback.format_exc()}"
        email.send_email(subject=email_subject, body=email_body)
