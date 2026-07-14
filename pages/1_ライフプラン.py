"""ライフプランシミュレーション（Streamlit マルチページ）。

既存ダッシュボード（app.py）とは独立したページ。専用サイドバーに調整UIを置き、
本体に サマリーカード / 資産推移＋年間支出グラフ / キャッシュフロー表 を描画する。

計算は lifeplan.py（純粋関数）、設定の読込は gsheet.load_sim_settings に委譲。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import analytics
import config
import gsheet
import lifeplan

st.set_page_config(
    page_title="ライフプランシミュレーション",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      /* ルートを大きめにして全体（テキスト・ウィジェット・カード）を比例拡大 */
      html { font-size: 18px; }
      .block-container { padding-top: 2rem; padding-bottom: 2rem; }
      div[data-testid="stMetric"] {
        background: #f7f9fc; border: 1px solid #e6ebf2;
        border-radius: 14px; padding: 14px 18px;
      }
      div[data-testid="stMetricLabel"] { opacity: 0.7; }
      div[data-testid="stMetricValue"] { font-size: 1.9rem; }
      h1, h2, h3 { letter-spacing: .02em; }

      /* データフレームは横スクロールで全列を確認できるようにする */
      div[data-testid="stDataFrame"] { overflow-x: auto; }

      /* --- スマートフォン（縦長・狭幅）向け最適化 --- */
      @media (max-width: 640px) {
        html { font-size: 15px; }
        .block-container {
          padding-top: 1rem; padding-bottom: 1rem;
          padding-left: .6rem; padding-right: .6rem;
        }
        div[data-testid="stMetricValue"] { font-size: 1.4rem; }
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

COLOR_ASSET = "#2E86DE"
COLOR_INCOME = "#27AE60"
COLOR_MILESTONE = "#8E44AD"
# 支出カテゴリの配色（積み上げ棒）
EXPENSE_COLORS = {
    "基本生活費": "#95A5A6",
    "住居費": "#34495E",
    "養育費": "#F1C40F",
    "教育費": "#E67E22",
    config.COL_HOME_MAINTENANCE: "#16A085",   # 持家修繕・家電買い換え（固定）
    config.COL_CHILD_INDEPENDENCE: "#8E44AD",  # 子ども大学卒業時支出
    config.COL_SPECIAL_EXPENSE: "#2980B9",     # 特別支出（タイムバケツ由来）
    "カスタム支出": "#C0392B",
}


# --- データ取得（キャッシュ）----------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client():
    return gsheet.get_client()


@st.cache_data(ttl=300, show_spinner="スプレッドシートを読み込み中…")
def load_all():
    client = get_client()
    df = gsheet.load_database(client)
    settings = gsheet.load_sim_settings(client)
    buckets = gsheet.load_time_buckets(client)  # タイムバケツ（特別支出の元データ）
    return df, settings, buckets


def yen(value: float) -> str:
    return f"¥{value:,.0f}"


# --- データ読み込み --------------------------------------------------------
st.title("🌱 ライフプランシミュレーション")

_c_reload, _c_reset = st.sidebar.columns(2)
if _c_reload.button("🔄 再読み込み", width="stretch"):
    load_all.clear()
    st.rerun()
if _c_reset.button("↩️ 入力を初期化", width="stretch",
                   help="保存済みの入力値を消去し、既定値に戻します。"):
    try:
        gsheet.save_sim_state({}, get_client())
    except Exception:  # noqa: BLE001
        pass
    load_all.clear()
    st.session_state.clear()
    st.rerun()

persist_enabled = True
try:
    df, settings, buckets = load_all()
except Exception as e:  # noqa: BLE001
    st.warning(
        "スプレッドシートに接続できませんでした。デフォルト値で続行します。\n\n"
        f"詳細: {getattr(e, '__cause__', '') or e}"
    )
    df, settings, buckets = pd.DataFrame(), config.default_sim_settings(), []
    persist_enabled = False  # 保存先が無いので永続化は無効

# タイムバケツ由来の特別支出（該当年齢の年に自動計上）
special_events = lifeplan.special_events_from_buckets(buckets)

# --- 入力値の永続化: セッション初回だけシートから最新の保存値を読み込む ------
# ウィジェットのキーはページ遷移で破棄されるため、遷移でも消えない通常の
# session_state 辞書（lp_state）を「入力値の正」として保持する。
# キャッシュを介さず読むので、他端末やリロード後も最新の保存値を取得できる。
if "lp_state" not in st.session_state:
    if persist_enabled:
        try:
            st.session_state["lp_state"] = gsheet.load_sim_state(get_client())
        except Exception:  # noqa: BLE001
            st.session_state["lp_state"] = {}
            persist_enabled = False
    else:
        st.session_state["lp_state"] = {}
lp_state = st.session_state["lp_state"]


def sv(key, default):
    """保存済み入力値を取り出す（未保存ならデフォルト）。"""
    val = lp_state.get(key, default)
    return val if val is not None else default

totals = analytics.monthly_total(df)
valid_totals = totals.dropna(subset=["_date"]) if not totals.empty else totals
if not valid_totals.empty:
    latest = valid_totals.iloc[-1]
    default_asset = float(latest["合計"])
    default_start_year = int(latest["_date"].year)
else:
    default_asset = 0.0
    default_start_year = datetime.now().year


# ===========================================================================
#  サイドバー: 調整パラメータ
# ===========================================================================
st.sidebar.title("⚙️ シミュレーション条件")

if persist_enabled:
    st.sidebar.caption("💾 変更した入力値は自動保存され、次回起動時に復元されます。")

st.sidebar.subheader("👤 基本設定")
start_asset = float(st.sidebar.number_input(
    "現在の資産残高（初期資産）", min_value=0,
    value=int(sv("start_asset", int(default_asset))), step=100_000, format="%d",
    help="資産管理ダッシュボードの最新月の総資産を初期値に参照しています。",
))
st.sidebar.caption(f"↑ ダッシュボード最新月の総資産: **{yen(default_asset)}**")
start_year = int(st.sidebar.number_input(
    "起点の西暦", min_value=2000, max_value=2100,
    value=int(sv("start_year", default_start_year)), step=1,
))
current_age = int(st.sidebar.number_input(
    "本人の現在年齢", min_value=0, max_value=90,
    value=int(sv("current_age", config.age_on(config.BIRTHDATE_SELF))), step=1,
    help=f"生年月日 {config.BIRTHDATE_SELF:%Y-%m-%d} から自動計算した満年齢を初期値にしています。",
))
retire_age = st.sidebar.slider(
    "リタイア年齢", min_value=40, max_value=75,
    value=int(sv("retire_age", config.DEFAULT_RETIRE_AGE)), step=1, format="%d 歳",
    key="retire_age",
)
pension_start_age = st.sidebar.slider(
    "年金受給開始年齢", min_value=60, max_value=75,
    value=int(sv("pension_start_age", config.DEFAULT_PENSION_START_AGE)),
    step=1, format="%d 歳", key="pension_start_age",
    help="65歳を基準に、繰り下げ(+0.7%/月)・繰り上げ(−0.4%/月)で年金額が自動増減します。",
)

st.sidebar.subheader("📈 運用利回り")
rate_before_pct = st.sidebar.slider(
    "リタイア前の運用利回り", min_value=0.0, max_value=10.0,
    value=float(sv("rate_before_pct", config.DEFAULT_RATE_BEFORE * 100)),
    step=0.5, format="%.1f%%",
)
rate_before = rate_before_pct / 100.0
rate_after_pct = st.sidebar.slider(
    "リタイア後の運用利回り", min_value=0.0, max_value=10.0,
    value=float(sv("rate_after_pct", config.DEFAULT_RATE_AFTER * 100)),
    step=0.5, format="%.1f%%",
)
rate_after = rate_after_pct / 100.0

st.sidebar.subheader("💴 収入")
annual_income = float(st.sidebar.number_input(
    "現役時代の年間手取り収入", min_value=0,
    value=int(sv("annual_income", config.DEFAULT_ANNUAL_INCOME)), step=100_000,
    key="annual_income",
))

# --- 年金（65歳ベース月額 ＋ 概算ボタン ＋ 受給開始年齢連動）--------------
# ベース月額は session_state で管理し、「概算する」ボタンから上書きできるようにする。
st.session_state.setdefault(
    "pension_base_monthly",
    int(sv("pension_base_monthly", config.DEFAULT_PENSION_MONTHLY)),
)


def _estimate_pension_base():
    """簡易式で65歳ベース月額を概算し、入力欄へ反映する。"""
    inc = float(st.session_state.get("annual_income", config.DEFAULT_ANNUAL_INCOME))
    rage = int(st.session_state.get("retire_age", config.DEFAULT_RETIRE_AGE))
    st.session_state["pension_base_monthly"] = int(round(
        lifeplan.estimate_base_pension_monthly(inc, rage)
    ))


st.sidebar.number_input(
    "年金（65歳時点の月額・ベース）", min_value=0, step=10_000,
    key="pension_base_monthly",
    help="65歳受給開始を基準(±0%)とした月額。受給開始年齢に応じて実受給額は自動増減します。",
)
st.sidebar.button(
    "🧮 年金額を概算する", width="stretch", on_click=_estimate_pension_base,
    help="基礎年金（夫婦2人分13万円/月）＋ 厚生年金（報酬比例）の簡易式でベース月額を自動セット。",
)
pension_base_monthly = float(st.session_state["pension_base_monthly"])
# 選択中の受給開始年齢での実受給額をプレビュー表示。
_factor = lifeplan.pension_factor(int(pension_start_age))
_paid = lifeplan.pension_monthly_paid(pension_base_monthly, int(pension_start_age))
st.sidebar.caption(
    f"→ {int(pension_start_age)}歳開始の実受給額: **{yen(_paid)}/月**"
    f"（65歳比 {(_factor - 1) * 100:+.1f}%）"
)

c_sev1, c_sev2 = st.sidebar.columns(2)
severance_age = int(c_sev1.number_input(
    "退職金 受取年齢", min_value=40, max_value=75,
    value=int(sv("severance_age", config.DEFAULT_SEVERANCE_AGE)), step=1,
))
severance_amount = float(c_sev2.number_input(
    "退職金額", min_value=0,
    value=int(sv("severance_amount", config.DEFAULT_SEVERANCE_AMOUNT)), step=100_000,
))

st.sidebar.subheader("🏠 住居費（住宅ローン）")
housing_current = float(st.sidebar.number_input(
    "現在の月々支払額", min_value=0,
    value=int(sv("housing_current", config.DEFAULT_HOUSING_CURRENT_MONTHLY)), step=1_000,
))
housing_revised = float(st.sidebar.number_input(
    "金利見直し後の月々支払額", min_value=0,
    value=int(sv("housing_revised", config.DEFAULT_HOUSING_REVISED_MONTHLY)), step=1_000,
))
housing_revise_age = int(st.sidebar.number_input(
    "金利見直しが適用される年齢", min_value=current_age, max_value=100,
    value=max(int(sv("housing_revise_age", config.DEFAULT_HOUSING_REVISE_AGE)), current_age),
    step=1,
))
housing_end_age = int(st.sidebar.number_input(
    "ローン支払い終了年齢", min_value=current_age, max_value=100,
    value=max(int(sv("housing_end_age", config.DEFAULT_HOUSING_END_AGE)), current_age),
    step=1,
    help="この年齢以降は住居費0円。",
))

st.sidebar.subheader("🍚 基本生活費")
st.sidebar.caption("夫婦の食費・光熱費等のベース。子どもの養育費は年齢に応じ自動加算されます。")
default_living = int(settings.get("平均生活費（月額）", config.DEFAULT_LIVING_COST_MONTHLY))
base_living = float(st.sidebar.slider(
    "基本生活費（月額・現役）", min_value=100_000, max_value=800_000,
    value=int(sv("base_living", default_living)), step=10_000, format="¥%d",
))
retire_living = float(st.sidebar.slider(
    "基本生活費（月額・リタイア後）", min_value=50_000, max_value=800_000,
    value=int(sv("retire_living", config.DEFAULT_RETIRE_LIVING_COST_MONTHLY)),
    step=10_000, format="¥%d",
))

st.sidebar.subheader("🎓 子どもの教育費")
st.sidebar.caption(
    f"各子が{config.CHILD_INDEPENDENCE_AGE}歳になる年に"
    f"「{config.COL_CHILD_INDEPENDENCE}」として"
    f"{config.CHILD_INDEPENDENCE_AMOUNT:,.0f}円が自動計上されます。"
)
saved_children = {c.get("name"): c for c in sv("children", []) if isinstance(c, dict)}
children: list[lifeplan.Child] = []
for name in config.CHILDREN:
    with st.sidebar.expander(name, expanded=(name == config.CHILDREN[0])):
        birth = config.CHILD_BIRTHDATES[name]
        saved_child = saved_children.get(name, {})
        saved_choices = saved_child.get("choices", {}) if isinstance(saved_child, dict) else {}
        age = st.number_input(
            f"{name}の現在年齢", min_value=0, max_value=30,
            value=int(saved_child.get("age", config.age_on(birth))), step=1,
            key=f"age_{name}",
            help=f"生年月日 {birth:%Y-%m-%d} から自動計算しています。",
        )
        choices = {}
        for stage in config.EDUCATION_STAGES:
            default_choice = saved_choices.get(stage, config.DEFAULT_SCHOOL_CHOICE[stage])
            if default_choice not in config.SCHOOL_TYPES:
                default_choice = config.DEFAULT_SCHOOL_CHOICE[stage]
            choices[stage] = st.selectbox(
                stage, config.SCHOOL_TYPES,
                index=config.SCHOOL_TYPES.index(default_choice),
                key=f"{name}_{stage}",
            )
        children.append(lifeplan.Child(name=name, current_age=int(age), choices=choices))

st.sidebar.subheader("👨‍👩‍👧‍👦 多子世帯支援")
apply_child_allowance = st.sidebar.checkbox(
    "児童手当を反映（第3子以降は増額）",
    value=bool(sv("apply_child_allowance", config.DEFAULT_APPLY_CHILD_ALLOWANCE)),
    help="0〜18歳に支給。第3子以降は月3万円。",
)
apply_univ_free_multi = st.sidebar.checkbox(
    "多子世帯の大学無償化を適用",
    value=bool(sv("apply_univ_free_multi", config.DEFAULT_APPLY_UNIV_FREE_MULTI)),
    help=f"扶養する子が{config.MULTI_CHILD_THRESHOLD}人以上いる年は、大学生の授業料を免除扱いにします。",
)

st.sidebar.subheader("🎉 カスタム・ライフイベント")
st.sidebar.caption(
    "車の買い替え・リフォーム等。「＋」で行を追加できます。"
    f"（持家修繕・家電は{config.HOME_MAINTENANCE_START_AGE}歳から"
    f"{config.HOME_MAINTENANCE_INTERVAL}年ごとに自動計上されます）"
)
_saved_events = sv("custom_events", [])
default_events = pd.DataFrame({
    "ラベル": pd.Series(
        [e.get("label", "") for e in _saved_events], dtype="string"),
    "年齢": pd.Series(
        [e.get("age") for e in _saved_events], dtype="Int64"),
    "区分": pd.Series(
        [e.get("kind", "支出") for e in _saved_events], dtype="string"),
    "金額": pd.Series(
        [e.get("amount") for e in _saved_events], dtype="Int64"),
})
edited_events = st.sidebar.data_editor(
    default_events,
    num_rows="dynamic",
    width="stretch",
    key="custom_events",
    column_config={
        "ラベル": st.column_config.TextColumn("ラベル"),
        "年齢": st.column_config.NumberColumn("年齢", min_value=0, max_value=120, step=1),
        "区分": st.column_config.SelectboxColumn("区分", options=["支出", "収入"]),
        "金額": st.column_config.NumberColumn("金額", min_value=0, step=100_000, format="¥%d"),
    },
)
custom_events: list[dict] = []
for _, r in edited_events.iterrows():
    if pd.isna(r.get("年齢")) or pd.isna(r.get("金額")):
        continue
    kind = r.get("区分") if r.get("区分") in ("支出", "収入") else "支出"
    custom_events.append({
        "label": str(r.get("ラベル") or "イベント"),
        "age": int(r["年齢"]),
        "kind": kind,
        "amount": float(r["金額"]),
    })


# ===========================================================================
#  入力値の永続化（変更があればスプレッドシートへ自動保存）
# ===========================================================================
current_state = {
    "start_asset": int(start_asset),
    "start_year": int(start_year),
    "current_age": int(current_age),
    "retire_age": int(retire_age),
    "pension_start_age": int(pension_start_age),
    "rate_before_pct": float(rate_before_pct),
    "rate_after_pct": float(rate_after_pct),
    "annual_income": int(annual_income),
    "pension_base_monthly": int(pension_base_monthly),
    "severance_age": int(severance_age),
    "severance_amount": int(severance_amount),
    "housing_current": int(housing_current),
    "housing_revised": int(housing_revised),
    "housing_revise_age": int(housing_revise_age),
    "housing_end_age": int(housing_end_age),
    "base_living": int(base_living),
    "retire_living": int(retire_living),
    "apply_child_allowance": bool(apply_child_allowance),
    "apply_univ_free_multi": bool(apply_univ_free_multi),
    "children": [
        {"name": c.name, "age": c.current_age, "choices": c.choices}
        for c in children
    ],
    "custom_events": custom_events,
}

if persist_enabled and current_state != lp_state:
    # まず「入力値の正」(セッション内)を更新しておく。これでページ遷移や
    # リロードでも維持される（シート保存が失敗しても当該セッションは保たれる）。
    st.session_state["lp_state"] = current_state
    lp_state = current_state
    try:
        gsheet.save_sim_state(current_state, get_client())
        st.sidebar.caption("✅ 入力を保存しました。")
    except Exception as e:  # noqa: BLE001
        st.sidebar.caption(f"⚠️ 保存に失敗しました（この端末では保持されます）: {e}")


# ===========================================================================
#  シミュレーション実行
# ===========================================================================
params = lifeplan.PlanParams(
    start_asset=start_asset,
    start_year=start_year,
    current_age=current_age,
    retire_age=int(retire_age),
    pension_start_age=int(pension_start_age),
    annual_income=annual_income,
    pension_monthly=pension_base_monthly,
    severance_age=severance_age,
    severance_amount=severance_amount,
    rate_before=rate_before,
    rate_after=rate_after,
    base_living_monthly=base_living,
    retire_living_monthly=retire_living,
    housing_current_monthly=housing_current,
    housing_revised_monthly=housing_revised,
    housing_revise_age=housing_revise_age,
    housing_end_age=housing_end_age,
    apply_child_allowance=apply_child_allowance,
    apply_univ_free_multi=apply_univ_free_multi,
    children=children,
    settings=settings,
    custom_events=custom_events,
    special_events=special_events,
)
sim = lifeplan.simulate(params)
events = lifeplan.milestones(params)


# ===========================================================================
#  メイングラフ: 資産推移（折れ線）＋ 年間収支（積み上げ棒＋収入線）
# ===========================================================================
st.subheader("資産推移と年間収支")

if special_events:
    _sp_total = sum(e["amount"] for e in special_events)
    st.caption(
        f"🪣 「タイムバケツ」で配置した {len(special_events)} 件（計 {yen(_sp_total)}）を"
        "「特別支出」として自動計上しています。編集はタイムバケツのページから。"
    )

fig = make_subplots(specs=[[{"secondary_y": True}]])

# 年間支出（カテゴリ別の積み上げ棒: 第1軸）
for cat, color in EXPENSE_COLORS.items():
    fig.add_trace(
        go.Bar(x=sim["西暦"], y=sim[cat], name=cat, marker_color=color, opacity=0.85),
        secondary_y=False,
    )

# 年間収入（折れ線: 第1軸）
fig.add_trace(
    go.Scatter(
        x=sim["西暦"], y=sim["年間収入"], name="年間収入",
        mode="lines", line=dict(color=COLOR_INCOME, width=2, dash="dot"),
    ),
    secondary_y=False,
)

# 総資産推移（折れ線: 第2軸）
fig.add_trace(
    go.Scatter(
        x=sim["西暦"], y=sim["期末資産残高"], name="年末資産残高",
        mode="lines", line=dict(color=COLOR_ASSET, width=3.5),
    ),
    secondary_y=True,
)

# マイルストーン（縦の点線＋ラベル）
year_min, year_max = int(sim["西暦"].min()), int(sim["西暦"].max())
for ev in events:
    if not (year_min <= ev["year"] <= year_max):
        continue
    fig.add_vline(x=ev["year"], line=dict(color=COLOR_MILESTONE, width=1, dash="dot"))
    fig.add_annotation(
        x=ev["year"], y=1.0, yref="paper", text=ev["label"],
        showarrow=False, textangle=-90, xanchor="left",
        font=dict(size=10, color=COLOR_MILESTONE),
    )

fig.update_layout(
    barmode="stack", height=520, margin=dict(l=10, r=10, t=40, b=80),
    template="plotly_white", hovermode="x unified",
    # 凡例（7項目）は下部に横並び。スマホでも折り返して収まる
    legend=dict(orientation="h", yanchor="top", y=-0.15, x=0),
)
fig.update_xaxes(title_text="西暦")
fig.update_yaxes(title_text="年間収支（円）", secondary_y=False)
fig.update_yaxes(title_text="資産残高（円）", secondary_y=True)
fig.add_hline(y=0, line=dict(color="#c0392b", width=1), secondary_y=True)

st.plotly_chart(fig, width="stretch", key="lifeplan_main")
st.caption(
    "積み上げ棒＝その年の支出内訳、緑の点線＝年間収入、青の実線＝年末資産残高。"
    "縦の紫点線は主要ライフイベントです。"
)

st.divider()


# ===========================================================================
#  キャッシュフロー詳細表（折りたたみ）
# ===========================================================================
with st.expander("📋 キャッシュフロー詳細表", expanded=False):
    cols = [
        "西暦", "年齢", "給与", "年金", "児童手当", "退職金", "カスタム収入",
        "運用益", "基本生活費", "住居費", "養育費", "教育費", "カスタム支出",
        config.COL_HOME_MAINTENANCE, config.COL_CHILD_INDEPENDENCE,
        config.COL_SPECIAL_EXPENSE,
        "年間収入", "年間支出", "期末資産残高",
    ]
    view = sim[cols].copy()
    money_cols = [c for c in cols if c not in ("西暦", "年齢")]
    st.dataframe(
        view.style.format({c: "¥{:,.0f}" for c in money_cols}),
        width="stretch", hide_index=True, height=460,
    )
