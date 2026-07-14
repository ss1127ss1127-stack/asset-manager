"""ライフプランシミュレーションの計算ロジック（純粋関数）。

UI（pages/1_ライフプラン.py）から切り離しておき、年齢↔学年↔各種費用の
マッピングと年次キャッシュフローの積み上げをここに集約する。
analytics.py と同じく Streamlit に依存しない。

年次モデル（各年の期初残高を base とする）:
    運用益   = base × 利回り（リタイア年齢を境に前/後で切替）
    収入計   = 給与 + 年金 + 児童手当 + 退職金 + カスタム収入
    支出計   = 基本生活費 + 住居費 + 養育費 + 教育費 + カスタム支出
    期末残高 = base + 運用益 + 収入計 − 支出計
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config


# ===========================================================================
#  入力パラメータ
# ===========================================================================
@dataclass
class Child:
    """子ども1人分の設定。choices は {ステージ名: '公立'|'私立'}。"""
    name: str
    current_age: int
    choices: dict[str, str]


@dataclass
class PlanParams:
    start_asset: float
    start_year: int
    current_age: int
    end_age: int = config.LIFE_END_AGE

    # ライフイベント年齢
    retire_age: int = config.DEFAULT_RETIRE_AGE
    pension_start_age: int = config.DEFAULT_PENSION_START_AGE

    # 収入
    annual_income: float = config.DEFAULT_ANNUAL_INCOME
    # pension_monthly は「65歳受給開始を基準とした月額」。実際の受給額は
    # pension_start_age に応じて pension_factor で自動増減する。
    pension_monthly: float = config.DEFAULT_PENSION_MONTHLY
    severance_age: int = config.DEFAULT_SEVERANCE_AGE
    severance_amount: float = config.DEFAULT_SEVERANCE_AMOUNT

    # 運用利回り（リタイア前 / 後）
    rate_before: float = config.DEFAULT_RATE_BEFORE
    rate_after: float = config.DEFAULT_RATE_AFTER

    # 基本生活費（リタイア前 / 後）月額
    base_living_monthly: float = config.DEFAULT_LIVING_COST_MONTHLY
    retire_living_monthly: float = config.DEFAULT_LIVING_COST_MONTHLY * config.RETIRE_LIVING_RATIO

    # 住居費（住宅ローン、変動金利）月額
    housing_current_monthly: float = config.DEFAULT_HOUSING_CURRENT_MONTHLY
    housing_revised_monthly: float = config.DEFAULT_HOUSING_REVISED_MONTHLY
    housing_revise_age: int = config.DEFAULT_HOUSING_REVISE_AGE
    housing_end_age: int = config.DEFAULT_HOUSING_END_AGE

    # 支援制度
    apply_child_allowance: bool = True
    apply_univ_free_multi: bool = False

    # 子ども / 教育費設定 / カスタムイベント
    children: list[Child] = field(default_factory=list)
    settings: dict[str, float] = field(default_factory=dict)
    # {'label': str, 'age': int, 'kind': '収入'|'支出', 'amount': float}
    custom_events: list[dict] = field(default_factory=list)


# ===========================================================================
#  年齢 → 各種費用のマッピング
# ===========================================================================
def stage_for_age(age: int) -> str | None:
    """その年齢の子どもが在籍する教育ステージ名を返す（範囲外は None）。"""
    for stage, (low, high) in config.STAGE_AGE_RANGE.items():
        if low <= age <= high:
            return stage
    return None


def education_cost_for_child(
    age: int, choices: dict[str, str], settings: dict[str, float]
) -> float:
    """ある年齢の子ども1人の、その年の教育費（授業料等・年額）。"""
    stage = stage_for_age(age)
    if stage is None:
        return 0.0
    school_type = choices.get(stage, "公立")
    return float(settings.get(config.edu_key(stage, school_type), 0.0))


def childcare_cost_for_age(age: int) -> float:
    """ある年齢の子ども1人の、その年の養育費（生活費への加算・年額）。"""
    for low, high, amount in config.CHILDCARE_BRACKETS:
        if low <= age <= high:
            return float(amount)
    return 0.0


def child_allowance_for_age(age: int, birth_order: int) -> float:
    """児童手当（年額）。birth_order は 1 始まり（第3子以降で増額）。"""
    if age < 0 or age > config.CHILD_ALLOWANCE_MAX_AGE:
        return 0.0
    if birth_order >= config.MULTI_CHILD_THRESHOLD:
        monthly = config.CHILD_ALLOWANCE_THIRD_MONTHLY
    elif age <= 2:
        monthly = config.CHILD_ALLOWANCE_UNDER3_MONTHLY
    else:
        monthly = config.CHILD_ALLOWANCE_STD_MONTHLY
    return float(monthly) * 12.0


# ===========================================================================
#  年金（受給開始年齢に連動した自動計算）
# ===========================================================================
def pension_factor(start_age: int) -> float:
    """受給開始年齢に応じた年金額の増減係数（65歳開始で 1.0）。

    - 66〜75歳（繰り下げ）: 1ヶ月遅らせるごとに +0.7%（70歳開始で +42%）
    - 60〜64歳（繰り上げ）: 1ヶ月早めるごとに −0.4%（60歳開始で −24%）
    """
    if start_age >= config.PENSION_BASE_AGE:
        months = (int(start_age) - config.PENSION_BASE_AGE) * 12
        return 1.0 + config.PENSION_DEFER_RATE_PER_MONTH * months
    months = (config.PENSION_BASE_AGE - int(start_age)) * 12
    return max(0.0, 1.0 - config.PENSION_EARLY_RATE_PER_MONTH * months)


def pension_monthly_paid(base_monthly: float, start_age: int) -> float:
    """実際に受給する年金月額（＝65歳ベース月額 × 受給開始年齢の増減係数）。"""
    return float(base_monthly) * pension_factor(int(start_age))


def estimate_base_pension_monthly(annual_income: float, retire_age: int) -> float:
    """65歳時点のベース年金月額を簡易式で概算する。

    基礎年金（夫婦2人分・一律） + 厚生年金（報酬比例部分）:
        厚生年金 = (年間手取り ÷ 0.8) ÷ 12 × (5.481/1000) × (リタイア年齢 − 22)
    """
    basic = float(config.PENSION_BASIC_MONTHLY_COUPLE)
    work_years = max(0, int(retire_age) - config.PENSION_WORK_START_AGE)
    gross_monthly = (float(annual_income) / config.PENSION_TAKEHOME_TO_GROSS) / 12.0
    kosei = gross_monthly * config.PENSION_KOSEI_COEFF * work_years
    return basic + kosei


# ===========================================================================
#  年次シミュレーション
# ===========================================================================
def simulate(params: PlanParams) -> pd.DataFrame:
    """開始年の総資産を起点に、終端年齢までの年次資産推移を計算する。

    戻り値の列:
        西暦, 年齢, 給与, 年金, 児童手当, 退職金, カスタム収入,
        運用益, 基本生活費, 住居費, 養育費, 教育費, カスタム支出,
        持家修繕・家電買い換え, 子ども大学卒業時支出,
        年間収入, 年間支出, 期末資産残高, _date
    """
    rows = []
    balance = float(params.start_asset)
    n_years = max(0, params.end_age - params.current_age)

    # 児童手当の第○子は、リストの並び（長男→次男→三男）を出生順とみなす。
    birth_order = {id(c): i + 1 for i, c in enumerate(params.children)}

    # 年金の実受給月額は受給開始年齢で決まる（毎年一定）ため、ループ外で1度だけ算出。
    paid_pension_monthly = pension_monthly_paid(
        params.pension_monthly, params.pension_start_age
    )

    for i in range(n_years + 1):
        year = params.start_year + i
        age = params.current_age + i
        working = age < params.retire_age

        # --- 運用益（期初残高に対して。利回りはリタイアを境に切替）---
        rate = params.rate_before if working else params.rate_after
        gain = balance * float(rate)

        # --- 収入 -------------------------------------------------------
        salary = float(params.annual_income) if working else 0.0
        pension = (
            paid_pension_monthly * 12.0
            if age >= params.pension_start_age
            else 0.0
        )
        severance = (
            float(params.severance_amount) if age == params.severance_age else 0.0
        )

        # 子ども関連（年齢はこの年の各子の年齢）
        child_ages = {id(c): c.current_age + i for c in params.children}
        dependents = sum(
            1 for a in child_ages.values() if 0 <= a <= config.DEPENDENT_MAX_AGE
        )
        univ_free = params.apply_univ_free_multi and dependents >= config.MULTI_CHILD_THRESHOLD

        allowance = 0.0
        childcare = 0.0
        education = 0.0
        for c in params.children:
            a = child_ages[id(c)]
            childcare += childcare_cost_for_age(a)
            edu = education_cost_for_child(a, c.choices, params.settings)
            if univ_free and stage_for_age(a) == "大学":
                edu = 0.0  # 多子世帯の大学無償化
            education += edu
            if params.apply_child_allowance:
                allowance += child_allowance_for_age(a, birth_order[id(c)])

        # --- 支出（基本生活費・住居費）--------------------------------
        base_living = (
            float(params.base_living_monthly)
            if working
            else float(params.retire_living_monthly)
        ) * 12.0
        housing = _housing_cost(age, params) * 12.0

        # --- カスタムイベント ------------------------------------------
        custom_income = sum(
            float(e["amount"])
            for e in params.custom_events
            if int(e["age"]) == age and e["kind"] == "収入"
        )
        custom_expense = sum(
            float(e["amount"])
            for e in params.custom_events
            if int(e["age"]) == age and e["kind"] == "支出"
        )

        # --- 定例支出（自動計上）--------------------------------------
        # 持家修繕・家電買い換え: 本人が35歳の年から10年ごとに固定計上。
        home_maint = (
            float(config.HOME_MAINTENANCE_AMOUNT)
            if age >= config.HOME_MAINTENANCE_START_AGE
            and (age - config.HOME_MAINTENANCE_START_AGE)
            % config.HOME_MAINTENANCE_INTERVAL == 0
            else 0.0
        )
        # 子ども大学卒業時支出: 各子が22歳になる年に100万円（人数分）。
        child_independence = sum(
            float(config.CHILD_INDEPENDENCE_AMOUNT)
            for a in child_ages.values()
            if a == config.CHILD_INDEPENDENCE_AGE
        )

        total_income = salary + pension + allowance + severance + custom_income
        total_expense = (
            base_living + housing + childcare + education + custom_expense
            + home_maint + child_independence
        )
        balance = balance + gain + total_income - total_expense

        rows.append(
            {
                "西暦": year,
                "年齢": age,
                "給与": salary,
                "年金": pension,
                "児童手当": allowance,
                "退職金": severance,
                "カスタム収入": custom_income,
                "運用益": gain,
                "基本生活費": base_living,
                "住居費": housing,
                "養育費": childcare,
                "教育費": education,
                "カスタム支出": custom_expense,
                config.COL_HOME_MAINTENANCE: home_maint,
                config.COL_CHILD_INDEPENDENCE: child_independence,
                "年間収入": total_income,
                "年間支出": total_expense,
                "期末資産残高": balance,
                "_date": pd.Timestamp(year=year, month=12, day=31),
            }
        )

    return pd.DataFrame(rows)


def _housing_cost(age: int, params: PlanParams) -> float:
    """その年齢の住居費（月額）。完済後は 0、見直し年齢以降は見直し後の額。"""
    if age >= params.housing_end_age:
        return 0.0
    if age >= params.housing_revise_age:
        return float(params.housing_revised_monthly)
    return float(params.housing_current_monthly)


# ===========================================================================
#  サマリー指標
# ===========================================================================
def asset_at_retirement(sim: pd.DataFrame, retire_age: int) -> float | None:
    """リタイア年齢時点の期末資産残高。該当年が無ければ None。"""
    hit = sim[sim["年齢"] == retire_age]
    if hit.empty:
        return None
    return float(hit.iloc[0]["期末資産残高"])


def asset_lifespan(sim: pd.DataFrame) -> dict:
    """資産寿命を判定する。

    戻り値:
        {"depleted": True,  "age": 枯渇年齢, "year": 西暦}          … 尽きる場合
        {"depleted": False, "final_age": 終端年齢, "final_asset": 額} … 安泰の場合
    """
    depleted = sim[sim["期末資産残高"] < 0]
    if not depleted.empty:
        first = depleted.iloc[0]
        return {"depleted": True, "age": int(first["年齢"]), "year": int(first["西暦"])}
    last = sim.iloc[-1]
    return {
        "depleted": False,
        "final_age": int(last["年齢"]),
        "final_asset": float(last["期末資産残高"]),
    }


# ===========================================================================
#  マイルストーン（縦の補助線）
# ===========================================================================
def milestones(params: PlanParams) -> list[dict]:
    """縦の補助線用のイベント一覧。各要素 {"year": 西暦, "label": ラベル}。"""
    events: list[dict] = []

    def year_of(age: int) -> int:
        return params.start_year + (age - params.current_age)

    events.append({"year": year_of(params.retire_age), "label": f"{params.retire_age}歳 リタイア"})
    events.append({"year": year_of(params.pension_start_age), "label": f"{params.pension_start_age}歳 年金開始"})
    events.append({"year": year_of(params.severance_age), "label": f"{params.severance_age}歳 退職金"})
    events.append({"year": year_of(params.housing_end_age), "label": "ローン完済"})

    univ_entry_age = config.STAGE_AGE_RANGE["大学"][0]  # 18
    for c in params.children:
        events.append({
            "year": params.start_year + (univ_entry_age - c.current_age),
            "label": f"{c.name} 大学入学",
        })

    for e in params.custom_events:
        events.append({"year": year_of(int(e["age"])), "label": str(e["label"])})

    return sorted(events, key=lambda e: e["year"])
