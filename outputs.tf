output "function_uri" {
  description = "デプロイされた Cloud Run functions の URI"
  value       = google_cloudfunctions2_function.notify.service_config[0].uri
}

output "service_account_email" {
  description = "関数およびスケジューラが使用するサービスアカウント"
  value       = google_service_account.function_sa.email
}

output "secret_id" {
  description = "Discord Webhook URL 用 Secret Manager シークレット ID"
  value       = data.google_secret_manager_secret.discord_webhook.secret_id
}

output "scheduler_job_name" {
  description = "作成された Cloud Scheduler ジョブ名"
  value       = google_cloud_scheduler_job.daily.name
}
