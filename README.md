# gcp-cost-notify

Google Cloud の日次利用料金を Discord に通知するシステム（[aws-cost-nofty](../aws-cost-nofty) の Google Cloud 版）。

## アーキテクチャ

```text
Cloud Scheduler (毎日 JST 9:00 / OIDC認証)
  -> Cloud Run functions (gcp-cost-notify / Python 3.12)
       |-- Secret Manager (Discord Webhook URL)
       |-- BigQuery (Cloud Billing Export テーブルを集計)
       `-> Discord Webhook (Embed 通知)
```

インフラはリポジトリ直下の Terraform ファイル（`main.tf` など）で定義し、Google Cloud **Infrastructure Manager**（Terraform ベースのマネージド IaC サービス）でデプロイ・state 管理を行います。

## 想定コスト

以下の無料枠（Free Tier）内に収まる規模のため、通常の個人利用では **月額 $0** で運用できます。

- Infrastructure Manager: デフォルトの Terraform 1.5.7（MPL 2.0）利用時は管理料無料（裏で動く Cloud Build・Cloud Storage も無料枠内）
- Cloud Run functions: 月 200 万リクエストまで無料
- BigQuery: ストレージ月 10 GB・クエリ月 1 TB まで無料
- Cloud Scheduler: 課金アカウントあたり月 3 ジョブまで無料
- Secret Manager: アクティブなシークレットバージョン月 6 つまで無料
- Cloud Storage: ソース zip 数 KB のみ（実質 $0）

## 事前準備

### 1. BigQuery への Cloud Billing エクスポートを有効化

Google Cloud コンソールで **お支払い > Billing エクスポート > BigQuery エクスポート** を開き、「標準使用量コスト」を有効にします。
設定後、BigQuery に `gcp_billing_export_v1_<BILLING_ACCOUNT_ID>` テーブルが作成されます（データが溜まり始めるまで数時間〜1 日程度かかります）。

### 2. Discord Webhook URL を Secret Manager に登録

`terraform.tfstate` に Webhook URL を残さないため、シークレットは Terraform 外で事前に作成します。

```bash
gcloud services enable secretmanager.googleapis.com --project=<PROJECT_ID>

printf '%s' 'https://discord.com/api/webhooks/...' | \
  gcloud secrets create discord-billing-webhook-url \
    --data-file=- \
    --project=<PROJECT_ID>
```

### 3. Infrastructure Manager 用の実行サービスアカウントを準備（初回のみ）

```bash
gcloud services enable config.googleapis.com cloudresourcemanager.googleapis.com --project=<PROJECT_ID>

gcloud iam service-accounts create infra-manager-sa \
  --display-name="Infrastructure Manager SA" \
  --project=<PROJECT_ID>

for role in roles/config.agent roles/editor roles/iam.securityAdmin; do
  gcloud projects add-iam-policy-binding <PROJECT_ID> \
    --member="serviceAccount:infra-manager-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
    --role="${role}" \
    --condition=None
done
```

## デプロイ（Infrastructure Manager）

### プレビュー（plan 相当・無料）

```bash
gcloud infra-manager previews create \
  --location=asia-northeast1 \
  --project=<PROJECT_ID> \
  --service-account="projects/<PROJECT_ID>/serviceAccounts/infra-manager-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --local-source=. \
  --input-values="project_id=<PROJECT_ID>,billing_export_table=<PROJECT_ID>.billing_export.gcp_billing_export_v1_XXXXXX_XXXXXX_XXXXXX"
```

### デプロイ実行

```bash
gcloud infra-manager deployments apply \
  projects/<PROJECT_ID>/locations/asia-northeast1/deployments/gcp-cost-notify \
  --service-account="projects/<PROJECT_ID>/serviceAccounts/infra-manager-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --local-source=. \
  --input-values="project_id=<PROJECT_ID>,billing_export_table=<PROJECT_ID>.billing_export.gcp_billing_export_v1_XXXXXX_XXXXXX_XXXXXX"
```

※ ローカルの `terraform` CLI で検証する場合は `terraform init && terraform validate` を実行できます。

## 動作確認

```bash
gcloud scheduler jobs run gcp-cost-notify-daily \
  --location=asia-northeast1 \
  --project=<PROJECT_ID>
```

Discord チャンネルに `🏦 Google Cloud 利用料金 日次レポート` が届けば完了です。
※ BigQuery エクスポートには数時間の反映ラグがあるため、朝 9:00 の集計では前日分の最後の数時間が未反映の場合があります。
