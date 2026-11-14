# AGENTS.md

## プロジェクト概要

Google Cloud の日次利用料金を Discord に通知する仕組み（`aws-cost-nofty` の Google Cloud 版）。
Cloud Billing の BigQuery エクスポートデータを集計し、毎日 JST 9:00 に Discord Webhook へ送信する。
インフラは Terraform 構成で定義し、Google Cloud Infrastructure Manager（またはローカル Terraform CLI）でデプロイする。

## 構成

- `function/main.py` - Cloud Run functions (2nd gen / Python 3.12) 本体
- `function/requirements.txt` - 依存パッケージ (`functions-framework`, `google-cloud-bigquery`)
- `versions.tf` / `variables.tf` / `main.tf` / `outputs.tf` - Infrastructure Manager / Terraform 構成
- `terraform.tfvars.example` - ローカル `terraform` 実行用の変数テンプレート
- `.gcloudignore` - Infrastructure Manager アップロード時の除外設定
- `README.md` - BigQuery エクスポート設定とデプロイ手順

主な Google Cloud リソース:

- Cloud Run functions (`gcp-cost-notify`, `asia-northeast1`): BigQuery から昨日・一昨日・今月累計を取得して Discord Webhook へ送信
- Cloud Scheduler (`gcp-cost-notify-daily`): 毎日 JST 9:00 (`0 9 * * *`) に OIDC 認証付きで関数を起動
- Secret Manager (`discord-billing-webhook-url`): Discord Webhook URL を保持（事前に手動作成し、Terraform では `data` 参照 + IAM 付与のみ行う）
- Cloud Storage (`<project_id>-gcp-cost-notify-source`): 関数ソース zip の格納バケット
- BigQuery: Cloud Billing エクスポート先データセット（コンソールから事前有効化が必要）

## コマンド

```bash
# Python 構文チェック
python3 -m py_compile function/main.py

# ローカルでの Terraform 構文チェック
terraform init
terraform validate

# Infrastructure Manager でのプレビュー（plan 相当）
gcloud infra-manager previews create \
  --location=asia-northeast1 \
  --project=<PROJECT_ID> \
  --service-account="projects/<PROJECT_ID>/serviceAccounts/infra-manager-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --local-source=. \
  --input-values="project_id=<PROJECT_ID>,billing_export_table=<BILLING_EXPORT_TABLE>"

# Infrastructure Manager でのデプロイ
gcloud infra-manager deployments apply \
  projects/<PROJECT_ID>/locations/asia-northeast1/deployments/gcp-cost-notify \
  --service-account="projects/<PROJECT_ID>/serviceAccounts/infra-manager-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --local-source=. \
  --input-values="project_id=<PROJECT_ID>,billing_export_table=<BILLING_EXPORT_TABLE>"

# 手動テスト実行
gcloud scheduler jobs run gcp-cost-notify-daily --location=asia-northeast1 --project=<PROJECT_ID>
```

## 開発ルール

- **デプロイ（`gcloud infra-manager deployments apply` / `terraform apply`）や Google Cloud リソースの変更は、ユーザーの明示的な依頼があるときだけ行う**
- Discord Webhook URL・`.env`・`terraform.tfvars`・`*.tfstate` は秘密情報。コード、コミット、ログ、出力に含めない
- 料金計算は `cost`（割引・クレジット適用前）と `cost + credits`（実費）の両方を扱う。月額 $10 クレジット枠と実費の両方が把握できるようにこの仕様を維持する
- 毎月 1 日は当月分が未集計になりやすいため、前月の累計にフォールバックする分岐を壊さない
- `gcloud` コマンドを変更・提案する前に `gcloud help <leaf_command>` で構文を確認する
