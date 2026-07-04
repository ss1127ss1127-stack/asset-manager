"""lifeplan の動作確認（合成データ）。Sheets API なしで実行可能。"""
import config
import lifeplan

s = config.default_sim_settings()
print("settings keys:", len(s), "| 大学_私立:", s["大学_私立"])

children = [
    lifeplan.Child("長男", 10, {"小学校": "公立", "中学校": "公立", "高校": "私立", "大学": "私立"}),
    lifeplan.Child("次男", 8, {"小学校": "公立", "中学校": "公立", "高校": "公立", "大学": "公立"}),
    lifeplan.Child("三男", 5, {"小学校": "私立", "中学校": "私立", "高校": "私立", "大学": "私立"}),
]

params = lifeplan.PlanParams(
    start_asset=30_000_000, start_year=2026, current_age=40,
    retire_age=50, pension_start_age=70,
    annual_income=7_200_000, pension_monthly=200_000,
    severance_age=50, severance_amount=1_000_000,
    rate_before=0.05, rate_after=0.03,
    base_living_monthly=300_000, retire_living_monthly=210_000,
    housing_current_monthly=72_153, housing_revised_monthly=90_000,
    housing_revise_age=55, housing_end_age=61,
    apply_child_allowance=True, apply_univ_free_multi=True,
    children=children, settings=s,
    custom_events=[{"label": "車買い替え", "age": 55, "kind": "支出", "amount": 3_000_000}],
)

sim = lifeplan.simulate(params)
print("rows:", len(sim))
show = ["西暦", "年齢", "給与", "年金", "児童手当", "運用益", "住居費", "養育費", "教育費", "期末資産残高"]
print(sim[show].head(12).to_string(index=False))
print("\n-- 住居費の切替確認（54→55→60→61歳）--")
print(sim[sim["年齢"].isin([54, 55, 60, 61])][["年齢", "住居費"]].to_string(index=False))
print("\n-- 年金空白期間（49→50→69→70歳）給与/年金 --")
print(sim[sim["年齢"].isin([49, 50, 69, 70])][["年齢", "給与", "年金", "運用益"]].to_string(index=False))
print("\nretire asset(50):", lifeplan.asset_at_retirement(sim, 50))
print("lifespan:", lifeplan.asset_lifespan(sim))
print("milestones:", lifeplan.milestones(params))
print("childcare 0/6/7/13/16/23:",
      [lifeplan.childcare_cost_for_age(a) for a in (0, 6, 7, 13, 16, 23)])
print("OK")
