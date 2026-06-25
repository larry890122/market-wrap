from __future__ import annotations

import argparse
import json
import os
import pathlib
import smtplib
from email.message import EmailMessage


LABELS_ZH = {
    "S&P 500": "S&P 500",
    "Dow Jones": "道瓊工業指數",
    "Nasdaq Composite": "那斯達克綜合指數",
    "Russell 2000": "羅素 2000",
    "FTSE 100": "FTSE 100",
    "CAC 40": "CAC 40",
    "DAX": "DAX",
    "Technology": "科技",
    "Financials": "金融",
    "Energy": "能源",
    "Health Care": "醫療保健",
    "Industrials": "工業",
    "Consumer Discretionary": "非必需消費",
    "Consumer Staples": "必需消費",
    "Utilities": "公用事業",
    "Materials": "原物料",
    "Real Estate": "不動產",
    "Communication Services": "通訊服務",
    "Apple": "Apple",
    "Microsoft": "Microsoft",
    "NVIDIA": "NVIDIA",
    "Amazon": "Amazon",
    "Alphabet": "Alphabet",
    "Meta": "Meta",
    "Tesla": "Tesla",
    "Broadcom": "Broadcom",
    "VIX": "VIX",
    "US 10Y Treasury": "美國 10 年期公債殖利率",
    "DXY": "美元指數",
    "WTI Front": "WTI 原油近月",
}


def parse_args() -> argparse.Namespace:
    root = pathlib.Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--us-payload-path", default=str(root / "output" / "latest_us_market_wrap.json"))
    parser.add_argument("--europe-payload-path", default=str(root / "output" / "latest_europe_market_snapshot.json"))
    parser.add_argument("--us-markdown-path", default=str(root / "output" / "latest_us_market_wrap.md"))
    parser.add_argument("--europe-markdown-path", default=str(root / "output" / "latest_europe_market_snapshot.md"))
    parser.add_argument("--recipient", default=os.environ.get("EMAIL_TO", ""))
    parser.add_argument("--sender", default=os.environ.get("GMAIL_SENDER", ""))
    parser.add_argument("--password", default=os.environ.get("GMAIL_APP_PASSWORD", ""))
    parser.add_argument("--smtp-host", default=os.environ.get("GMAIL_SMTP_HOST", "smtp.gmail.com"))
    parser.add_argument("--smtp-port", type=int, default=int(os.environ.get("GMAIL_SMTP_PORT", "465")))
    parser.add_argument("--print-only", action="store_true")
    return parser.parse_args()


def load_payload(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_label(name: str) -> str:
    return LABELS_ZH.get(name, name)


def format_last(row: dict) -> str:
    style = row.get("ChangeStyle", "pct")
    last = row.get("Last")
    if last is None:
        return "n/a"
    if style == "bps":
        return f"{last:.3f}%"
    return f"{last:.2f}"


def format_change(row: dict) -> str:
    style = row.get("ChangeStyle", "pct")
    if style == "abs":
        return f"{row.get('Change', 0):+,.2f}"
    if style == "bps":
        return f"{row.get('Change', 0) * 100:+,.2f} bp"
    return f"{row.get('ChangePct', 0):+,.2f}%"


def format_row(row: dict) -> str:
    return f"- {get_label(row.get('Name', 'Unknown'))}: {format_last(row)} ({format_change(row)})"


def ranked_line(rows: list[dict]) -> str:
    if not rows:
        return "無資料"
    return "、".join(f"{get_label(row.get('Name', 'Unknown'))} {format_change(row)}" for row in rows)


def build_market_section(title: str, payload: dict) -> list[str]:
    lines: list[str] = [title]
    lines.append(f"日期: {payload.get('summaryDate', 'n/a')}")
    if payload.get("priceSource"):
        lines.append(f"股價來源: {payload['priceSource']}")
    if payload.get("oneLineSummary"):
        lines.append(f"摘要: {payload['oneLineSummary']}")
    lines.append("")
    lines.append("主要指數")
    for row in payload.get("indices") or []:
        lines.append(format_row(row))

    top_sectors = payload.get("topSectors") or []
    weakest_sectors = payload.get("weakestSectors") or []
    megacap_leaders = payload.get("megacapLeaders") or []
    megacap_laggards = payload.get("megacapLaggards") or []
    macro_rows = payload.get("macro") or []

    if macro_rows:
        lines.append("")
        lines.append("跨資產觀察")
        for row in macro_rows:
            lines.append(format_row(row))

    if top_sectors or weakest_sectors:
        lines.append("")
        lines.append(f"領漲族群: {ranked_line(top_sectors)}")
        lines.append(f"領跌族群: {ranked_line(weakest_sectors)}")

    if megacap_leaders or megacap_laggards:
        lines.append("")
        lines.append(f"大型股強勢: {ranked_line(megacap_leaders)}")
        lines.append(f"大型股弱勢: {ranked_line(megacap_laggards)}")

    return lines


def build_subject(us_payload: dict, europe_payload: dict) -> str:
    us_date = us_payload.get("summaryDate", "")
    eu_date = europe_payload.get("summaryDate", "")
    if us_date and us_date == eu_date:
        return f"每日市場晨報 | {us_date}"
    if us_date and eu_date:
        return f"每日市場晨報 | US {us_date} | EU {eu_date}"
    return "每日市場晨報"


def build_body(us_payload: dict, europe_payload: dict) -> str:
    lines: list[str] = []
    lines.append("每日市場晨報")
    lines.append("")
    lines.extend(build_market_section("美股", us_payload))
    lines.append("")
    lines.extend(build_market_section("歐股", europe_payload))
    return "\n".join(lines)


def attach_file(message: EmailMessage, path: pathlib.Path) -> None:
    if not path.exists():
        return
    data = path.read_bytes()
    message.add_attachment(
        data,
        maintype="text",
        subtype="markdown" if path.suffix.lower() == ".md" else "plain",
        filename=path.name,
    )


def send_email(
    *,
    smtp_host: str,
    smtp_port: int,
    sender: str,
    password: str,
    recipient: str,
    subject: str,
    body: str,
    attachments: list[pathlib.Path],
) -> None:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    for attachment in attachments:
        attach_file(message, attachment)

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(sender, password)
        server.send_message(message)


def main() -> None:
    args = parse_args()
    us_payload = load_payload(pathlib.Path(args.us_payload_path))
    europe_payload = load_payload(pathlib.Path(args.europe_payload_path))
    subject = build_subject(us_payload, europe_payload)
    body = build_body(us_payload, europe_payload)

    if args.print_only:
        print(subject)
        print("")
        print(body)
        return

    if not args.recipient:
        raise ValueError("Missing recipient. Set --recipient or EMAIL_TO.")
    if not args.sender:
        raise ValueError("Missing sender. Set --sender or GMAIL_SENDER.")
    if not args.password:
        raise ValueError("Missing app password. Set --password or GMAIL_APP_PASSWORD.")

    attachments = [
        pathlib.Path(args.us_markdown_path),
        pathlib.Path(args.europe_markdown_path),
    ]

    send_email(
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        sender=args.sender,
        password=args.password,
        recipient=args.recipient,
        subject=subject,
        body=body,
        attachments=attachments,
    )

    print(f"Sent market wrap email to {args.recipient}.")


if __name__ == "__main__":
    main()
