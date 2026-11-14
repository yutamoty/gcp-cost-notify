variable "project_id" {
  description = "Google Cloud プロジェクト ID"
  type        = string
}

variable "region" {
  description = "リソースを配置するリージョン"
  type        = string
  default     = "asia-northeast1"
}

variable "billing_export_table" {
  description = "Cloud Billing BigQuery エクスポートテーブル (project.dataset.table)"
  type        = string
}

variable "function_name" {
  description = "Cloud Run functions の関数名"
  type        = string
  default     = "gcp-cost-notify"
}

variable "scheduler_job_name" {
  description = "Cloud Scheduler ジョブ名"
  type        = string
  default     = "gcp-cost-notify-daily"
}

variable "schedule" {
  description = "Cloud Scheduler の cron 式"
  type        = string
  default     = "0 9 * * *"
}

variable "secret_name" {
  description = "Discord Webhook URL を格納した既存の Secret Manager シークレット ID"
  type        = string
  default     = "discord-billing-webhook-url"
}

variable "service_account_name" {
  description = "実行・スケジューラ起動用のサービスアカウント ID"
  type        = string
  default     = "gcp-cost-notify-sa"
}

variable "alert_threshold" {
  description = "実費警告カラーに切り替える月額しきい値 (USD)"
  type        = number
  default     = 5
}
