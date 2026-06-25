# Daily Market Wrap GitHub Package

這個資料夾是可直接放上 GitHub 的精簡版本，使用 Yahoo Finance 抓股價，並由 GitHub Actions 每天上午 8:00（台北時間）自動產出市場晨報，再寄到 Gmail。

## 內含檔案

- `generate_market_wrap_yahoo.py`
- `market_wrap_yahoo_config.json`
- `run_daily_market_wrap.py`
- `send_market_wrap_email.py`
- `.github/workflows/market-wrap-yahoo.yml`

## 上傳到 GitHub 後要做的事

1. 建立一個新的 GitHub repository。
2. 把這個資料夾內的檔案全部上傳到 repository 根目錄。
3. 確認 `.github/workflows/market-wrap-yahoo.yml` 已經在預設分支上。

## GitHub Secrets

到 GitHub：
`Settings` -> `Secrets and variables` -> `Actions`

新增以下三個 secrets：

- `EMAIL_TO`：收件的 Gmail
- `GMAIL_SENDER`：寄件的 Gmail
- `GMAIL_APP_PASSWORD`：寄件 Gmail 的 App Password

## Gmail 設定

寄件 Gmail 需要：

1. 開啟兩步驟驗證
2. 建立 App Password
3. 把該密碼填進 `GMAIL_APP_PASSWORD`

## 排程時間

工作流使用 UTC cron：

- `0 0 * * *`

這等於台北時間每天 `08:00`。

## 本地測試

```powershell
python .\run_daily_market_wrap.py --target-date 2026-06-24
python .\send_market_wrap_email.py --print-only
```
