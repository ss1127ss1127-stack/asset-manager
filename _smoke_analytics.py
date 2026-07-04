"""analytics の動作確認（合成データ）。Sheets API なしで実行可能。"""
import pandas as pd
import analytics
import config

rows = [
    ("2024-01", "夫", "銀行A", "現金", 1_000_000, ""),
    ("2024-01", "夫", "証券A", "投資信託", 500_000, ""),
    ("2024年6月", "妻", "銀行B", "普通預金", 1_200_000, ""),
    ("2024年6月", "夫", "証券A", "株式", 800_000, ""),
    ("2024/12", "夫", "銀行A", "現金", 1_500_000, ""),
    ("2024/12", "夫", "証券A", "投資信託", 1_300_000, ""),
    ("2024/12", "妻", "保険C", "学資保険", 300_000, ""),
]
df = pd.DataFrame(rows, columns=config.DATABASE_COLUMNS)

print("年月の並び:", analytics.sorted_year_months(df))
print("\n総資産推移:")
print(analytics.monthly_total(df)[["年月", "合計"]].to_string(index=False))

print("\n分類判定:")
for c in ["現金", "普通預金", "投資信託", "株式", "学資保険", "謎カテゴリ"]:
    print(f"  {c} -> {analytics.classify_asset(c)}")

print("\n安全/リスク（2024/12）:")
print(analytics.safe_risk_breakdown(df, "2024/12").to_string())

print("\nポートフォリオ（2024/12）:")
print(analytics.portfolio_by_category(df, "2024/12").to_string())

totals = analytics.monthly_total(df)
print(f"\n月平均増加額: {analytics.average_monthly_increase(totals):,.0f} 円/月")
proj = analytics.project_future(totals, annual_rate=0.05, years=20)
print(f"20年後予測: {proj.iloc[-1]['予測額']:,.0f} 円 （行数 {len(proj)}）")
print("OK")
