#!/usr/bin/env python3
"""
千葉県のレギュラーガソリン価格をgogo.gsから取得するスクリプト
"""

import requests
from bs4 import BeautifulSoup
import sys
from datetime import datetime
import re


def fetch_gas_price(year: int, month: int, day: int = 10, *, fallback_days: int = 0) -> dict:
    """
    指定された日付のガソリン価格レポートから千葉県のレギュラー価格を取得
    
    Args:
        year: 年（例: 2026）
        month: 月（例: 1）
        day: 日（デフォルト: 10）
        fallback_days: 404の場合に遡って試す日数（例: 2 なら day, day-1, day-2 を試す）
    
    Returns:
        dict: {"price": 価格, "date": 日付文字列, "url": レポートURL, "year": 年, "month": 月, "day": 日}
    """
    if fallback_days < 0:
        raise ValueError("fallback_days must be >= 0")

    # Try the requested date first, then go backwards if 404.
    # gogo.gs reports may not be published exactly on the 10th; fallback supports 9th/8th etc.
    for try_day in range(day, max(0, day - fallback_days) - 1, -1):
        if try_day <= 0:
            break
        url = f"https://gogo.gs/news/report/{year}-{month}-{try_day:02d}"

        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 404:
                continue
            response.raise_for_status()
        except requests.RequestException as e:
            raise Exception(f"ページの取得に失敗しました: {e}") from e

        soup = BeautifulSoup(response.text, 'html.parser')
    
        # テーブルから千葉県の行を探す
        tables = soup.find_all('table')

        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    # 最初のセルが千葉県かチェック
                    first_cell = cells[0].get_text(strip=True)
                    if '千葉県' in first_cell or first_cell == '千葉県':
                        # 2番目のセルがレギュラー価格
                        price_text = cells[1].get_text(strip=True)
                        # 数字部分のみ抽出（前週比を除く）
                        match = re.match(r'([\d.]+)', price_text)
                        if match:
                            price = float(match.group(1))
                            return {
                                "price": price,
                                "date": f"{year}年{month}月{try_day}日",
                                "url": url,
                                "year": year,
                                "month": month,
                                "day": try_day,
                            }
    
    raise Exception("千葉県のガソリン価格が見つかりませんでした")


def main():
    """メイン処理"""
    if len(sys.argv) >= 3:
        year = int(sys.argv[1])
        month = int(sys.argv[2])
        day = int(sys.argv[3]) if len(sys.argv) >= 4 else 10
        fallback_days = int(sys.argv[4]) if len(sys.argv) >= 5 else 2
    else:
        # デフォルトは現在の月
        now = datetime.now()
        year = now.year
        month = now.month
        day = 10
        fallback_days = 2
    
    try:
        result = fetch_gas_price(year, month, day, fallback_days=fallback_days)
        print(f"日付: {result['date']}")
        print(f"千葉県レギュラー価格: {result['price']}円")
        print(f"URL: {result['url']}")
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
