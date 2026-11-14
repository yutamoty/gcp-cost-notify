from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import urllib.request

import functions_framework
from google.cloud import bigquery

JST = timezone(timedelta(hours=9))


def format_amount(amount: Decimal, currency: str, signed: bool = False) -> str:
    """Format monetary amount based on currency code."""
    sign = "+" if signed and amount > 0 else "-" if amount < 0 else ""
    abs_val = abs(amount)
    if currency == "JPY":
        return f"{sign}¥{abs_val:,.0f}"
    if currency == "USD":
        return f"{sign}${abs_val:,.2f}"
    return f"{sign}{abs_val:,.2f} {currency}"


def send_discord_embed(webhook_url: str, embed: dict) -> None:
    """Send a single embed payload to a Discord Webhook URL."""
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "gcp-cost-notify/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Discord webhook returned HTTP {resp.status}")


def query_billing_summary(
    client: bigquery.Client,
    table_fqn: str,
    today: date,
) -> dict:
    """Query yesterday, day-before-yesterday, and monthly billing totals from BigQuery."""
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)

    month_start = today.replace(day=1)
    if month_start == today:
        target_month_start = (month_start - timedelta(days=1)).replace(day=1)
        target_month_end = month_start
        is_prev_month = True
    else:
        target_month_start = month_start
        target_month_end = today
        is_prev_month = False

    invoice_month = target_month_start.strftime("%Y%m")

    sql = f"""
    WITH base AS (
      SELECT
        DATE(usage_start_time, "Asia/Tokyo") AS usage_date,
        invoice.month AS invoice_month,
        currency,
        CAST(cost AS NUMERIC) AS gross_cost,
        CAST(
          cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) AS c), 0)
          AS NUMERIC
        ) AS net_cost
      FROM `{table_fqn}`
      WHERE _PARTITIONTIME >= TIMESTAMP_SUB(TIMESTAMP(@month_start), INTERVAL 2 DAY)
    )
    SELECT
      ANY_VALUE(currency) AS currency,
      IFNULL(SUM(IF(usage_date = @yesterday, gross_cost, 0)), 0) AS yesterday_gross,
      IFNULL(SUM(IF(usage_date = @yesterday, net_cost, 0)), 0) AS yesterday_net,
      IFNULL(SUM(IF(usage_date = @day_before_yesterday, gross_cost, 0)), 0) AS prev_gross,
      IFNULL(SUM(IF(usage_date = @day_before_yesterday, net_cost, 0)), 0) AS prev_net,
      IFNULL(SUM(IF(invoice_month = @invoice_month AND usage_date < @today, gross_cost, 0)), 0) AS monthly_gross,
      IFNULL(SUM(IF(invoice_month = @invoice_month AND usage_date < @today, net_cost, 0)), 0) AS monthly_net
    FROM base
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("month_start", "DATE", target_month_start),
            bigquery.ScalarQueryParameter("yesterday", "DATE", yesterday),
            bigquery.ScalarQueryParameter("day_before_yesterday", "DATE", day_before_yesterday),
            bigquery.ScalarQueryParameter("today", "DATE", today),
            bigquery.ScalarQueryParameter("invoice_month", "STRING", invoice_month),
        ]
    )

    rows = list(client.query(sql, job_config=job_config).result())
    if not rows:
        return {
            "currency": "USD",
            "yesterday": yesterday,
            "target_month_start": target_month_start,
            "is_prev_month": is_prev_month,
            "yesterday_gross": Decimal("0"),
            "yesterday_net": Decimal("0"),
            "prev_gross": Decimal("0"),
            "prev_net": Decimal("0"),
            "monthly_gross": Decimal("0"),
            "monthly_net": Decimal("0"),
        }

    row = rows[0]
    return {
        "currency": row["currency"] or "USD",
        "yesterday": yesterday,
        "target_month_start": target_month_start,
        "is_prev_month": is_prev_month,
        "yesterday_gross": Decimal(str(row["yesterday_gross"])),
        "yesterday_net": Decimal(str(row["yesterday_net"])),
        "prev_gross": Decimal(str(row["prev_gross"])),
        "prev_net": Decimal(str(row["prev_net"])),
        "monthly_gross": Decimal(str(row["monthly_gross"])),
        "monthly_net": Decimal(str(row["monthly_net"])),
    }


@functions_framework.http
def notify_cost(request):
    """HTTP entrypoint triggered by Cloud Scheduler to post Google Cloud daily cost to Discord."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    table_fqn = os.environ.get("BILLING_EXPORT_TABLE", "").strip()
    alert_threshold = Decimal(os.environ.get("ALERT_THRESHOLD", "5"))

    if not webhook_url:
        return (json.dumps({"error": "DISCORD_WEBHOOK_URL is not set"}), 500)
    if not table_fqn:
        return (json.dumps({"error": "BILLING_EXPORT_TABLE is not set"}), 500)

    now_jst = datetime.now(JST)
    today = now_jst.date()

    try:
        client = bigquery.Client()
        summary = query_billing_summary(client, table_fqn, today)

        currency = summary["currency"]
        yesterday = summary["yesterday"]
        y_net = summary["yesterday_net"]
        y_gross = summary["yesterday_gross"]
        p_net = summary["prev_net"]
        m_net = summary["monthly_net"]
        m_gross = summary["monthly_gross"]

        diff_net = y_net - p_net
        change_symbol = "📈" if diff_net > 0 else "📉" if diff_net < 0 else "➡️"

        monthly_label = (
            f"📊 {summary['target_month_start'].strftime('%Y年%m月')} 累計"
            if summary["is_prev_month"]
            else f"📊 今月の累計 ({summary['target_month_start'].strftime('%m月%d日')}〜)"
        )

        embed = {
            "title": "🏦 Google Cloud 利用料金 日次レポート",
            "color": 0x4285F4,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [
                {
                    "name": f"📅 {yesterday.strftime('%Y年%m月%d日')} の利用料金",
                    "value": (
                        f"**{format_amount(y_net, currency)}**"
                        f" (割引前: {format_amount(y_gross, currency)})"
                    ),
                    "inline": True,
                },
                {
                    "name": f"{change_symbol} 前日比 (実費)",
                    "value": format_amount(diff_net, currency, signed=True),
                    "inline": True,
                },
                {
                    "name": monthly_label,
                    "value": (
                        f"**{format_amount(m_net, currency)}**"
                        f" (割引前: {format_amount(m_gross, currency)})"
                    ),
                    "inline": False,
                },
            ],
            "footer": {
                "text": "Google Cloud Billing Export (BigQuery) | 反映に数時間のラグがあります"
            },
        }

        if y_net > alert_threshold:
            embed["color"] = 0xFF0000
            embed["fields"].insert(
                0,
                {
                    "name": "⚠️ 高額利用アラート",
                    "value": f"昨日の実費が {format_amount(alert_threshold, currency)} を超えています",
                    "inline": False,
                },
            )

        send_discord_embed(webhook_url, embed)

        return (
            json.dumps(
                {
                    "message": "Notification sent successfully",
                    "currency": currency,
                    "yesterday_net": float(y_net),
                    "yesterday_gross": float(y_gross),
                    "monthly_net": float(m_net),
                    "monthly_gross": float(m_gross),
                }
            ),
            200,
        )

    except Exception as exc:
        print(f"Error: {exc}")
        error_embed = {
            "title": "❌ Google Cloud 請求額通知エラー",
            "description": f"エラーが発生しました: {exc}",
            "color": 0xFF0000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            send_discord_embed(webhook_url, error_embed)
        except Exception as notify_exc:
            print(f"Failed to send error notification: {notify_exc}")
        return (json.dumps({"error": str(exc)}), 500)
