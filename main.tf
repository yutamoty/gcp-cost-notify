locals {
  apis = toset([
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "bigquery.googleapis.com",
    "artifactregistry.googleapis.com",
  ])
}

resource "google_project_service" "apis" {
  for_each = local.apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "function_sa" {
  account_id   = var.service_account_name
  display_name = "Google Cloud Cost Notify"
}

resource "google_project_iam_member" "bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.function_sa.email}"
}

resource "google_project_iam_member" "bq_data_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.function_sa.email}"
}

data "google_secret_manager_secret" "discord_webhook" {
  project   = var.project_id
  secret_id = var.secret_name

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "secret_accessor" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.discord_webhook.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.function_sa.email}"
}

data "archive_file" "function_source" {
  type        = "zip"
  source_dir  = "${path.module}/function"
  output_path = "/tmp/function-source.zip"
}

resource "google_storage_bucket" "source_bucket" {
  name                        = "${var.project_id}-${var.function_name}-source"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
}

resource "google_storage_bucket_object" "function_zip" {
  name   = "function-source-${data.archive_file.function_source.output_md5}.zip"
  bucket = google_storage_bucket.source_bucket.name
  source = data.archive_file.function_source.output_path
}

resource "google_service_account" "build_sa" {
  account_id   = "${var.service_account_name}-build"
  display_name = "Google Cloud Cost Notify Build"
}

resource "google_project_iam_member" "build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.build_sa.email}"
}

resource "google_project_iam_member" "build_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.build_sa.email}"
}

resource "google_project_iam_member" "build_storage_object_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.build_sa.email}"
}

resource "time_sleep" "wait_build_iam" {
  create_duration = "60s"

  depends_on = [
    google_project_iam_member.build_log_writer,
    google_project_iam_member.build_artifact_registry_writer,
    google_project_iam_member.build_storage_object_admin,
  ]
}

resource "google_cloudfunctions2_function" "notify" {
  name        = var.function_name
  location    = var.region
  description = "Google Cloud の日次利用料金を Discord に通知する"

  build_config {
    runtime         = "python312"
    entry_point     = "notify_cost"
    service_account = google_service_account.build_sa.id

    source {
      storage_source {
        bucket = google_storage_bucket.source_bucket.name
        object = google_storage_bucket_object.function_zip.name
      }
    }
  }

  service_config {
    max_instance_count             = 1
    available_memory               = "256M"
    timeout_seconds                = 60
    all_traffic_on_latest_revision = true
    service_account_email          = google_service_account.function_sa.email

    environment_variables = {
      BILLING_EXPORT_TABLE = var.billing_export_table
      ALERT_THRESHOLD      = tostring(var.alert_threshold)
    }

    secret_environment_variables {
      key        = "DISCORD_WEBHOOK_URL"
      project_id = var.project_id
      secret     = data.google_secret_manager_secret.discord_webhook.secret_id
      version    = "latest"
    }
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.secret_accessor,
    time_sleep.wait_build_iam,
  ]
}

resource "google_cloudfunctions2_function_iam_member" "invoker" {
  project        = google_cloudfunctions2_function.notify.project
  location       = google_cloudfunctions2_function.notify.location
  cloud_function = google_cloudfunctions2_function.notify.name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${google_service_account.function_sa.email}"
}

resource "google_cloud_run_service_iam_member" "run_invoker" {
  project  = google_cloudfunctions2_function.notify.project
  location = google_cloudfunctions2_function.notify.location
  service  = google_cloudfunctions2_function.notify.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.function_sa.email}"
}

resource "google_cloud_scheduler_job" "daily" {
  name        = var.scheduler_job_name
  description = "毎日 JST 9:00 に gcp-cost-notify を起動する"
  schedule    = var.schedule
  time_zone   = "Asia/Tokyo"
  project     = var.project_id
  region      = var.region

  http_target {
    uri         = google_cloudfunctions2_function.notify.service_config[0].uri
    http_method = "POST"

    oidc_token {
      audience              = "${google_cloudfunctions2_function.notify.service_config[0].uri}/"
      service_account_email = google_service_account.function_sa.email
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloudfunctions2_function_iam_member.invoker,
    google_cloud_run_service_iam_member.run_invoker,
  ]
}
