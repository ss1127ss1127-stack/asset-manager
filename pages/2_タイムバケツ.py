"""タイムバケツ（Time Bucket）ページ（Streamlit マルチページ）。

「いつか / いつまでにやりたいこと」を年代別バケツ（カンバン列）に配置する。
配置したアイテムの予定金額は、ライフプランシミュレーションの「特別支出」として
自動連動する（gsheet 経由で夫婦共有。lifeplan.special_events_from_buckets で変換）。

ドラッグ＆ドロップの代替として、カード内の年代セレクトボックスで移動する。
データは Google スプレッドシートの『タイムバケツ』シートに保存し、
夫のスマホで追加した内容が妻のアクセス時にも同期表示される。
"""

from __future__ import annotations

import uuid

import streamlit as st

import config
import gsheet
import lifeplan

st.set_page_config(
    page_title="タイムバケツ",
    page_icon="🪣",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      html { font-size: 18px; }
      .block-container { padding-top: 2rem; padding-bottom: 2rem; }
      /* カンバン列の見出し */
      .tb-col-head {
        font-weight: 700; font-size: 1.05rem; padding: 6px 10px;
        border-radius: 10px 10px 0 0; color: #fff; margin-bottom: .4rem;
      }
      .tb-col-total { font-size: .8rem; opacity: .95; font-weight: 500; }
      div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
      @media (max-width: 640px) {
        html { font-size: 15px; }
        .block-container { padding-left: .6rem; padding-right: .6rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# バケツごとの見出し色（未分類は中立グレー、年代は時間軸で暖色→寒色）
BUCKET_COLORS = {
    "未分類": "#7F8C8D",
    "30代": "#E67E22",
    "40代": "#E74C3C",
    "50代": "#8E44AD",
    "60代": "#2980B9",
    "70代以上": "#16A085",
}


def yen(value: float) -> str:
    return f"¥{value:,.0f}"


# --- データ層（キャッシュ）-------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client():
    return gsheet.get_client()


@st.cache_data(ttl=300, show_spinner="タイムバケツを読み込み中…")
def load_items_cached():
    """スプレッドシートからアイテム一覧を読み込む（夫婦共有の同期ポイント）。"""
    return gsheet.load_time_buckets(get_client())


def persist(items: list[dict]) -> bool:
    """アイテム一覧を保存し、全ページのキャッシュを無効化する。

    キャッシュをクリアすることで、ライフプランページの「特別支出」も
    ページ切り替え時に最新の内容で再計算される。
    """
    try:
        gsheet.save_time_buckets(items, get_client())
    except Exception as e:  # noqa: BLE001
        st.session_state["_tb_error"] = str(e)
        return False
    st.cache_data.clear()
    st.session_state["_tb_error"] = None
    return True


# --- 初期ロード ------------------------------------------------------------
st.title("🪣 タイムバケツ")
st.caption(
    "「人生でやりたいこと」を年代のバケツに入れていきましょう。"
    "配置した予定金額は、ライフプランの **特別支出** としてその年代（中央の年齢）に"
    "自動計上されます。データは夫婦で共有・同期されます。"
)

persist_enabled = True
if "tb_items" not in st.session_state:
    try:
        st.session_state["tb_items"] = load_items_cached()
    except Exception as e:  # noqa: BLE001
        st.warning(
            "スプレッドシートに接続できませんでした。保存/同期は無効です。\n\n"
            f"詳細: {getattr(e, '__cause__', '') or e}"
        )
        st.session_state["tb_items"] = []
        persist_enabled = False
st.session_state.setdefault("_tb_error", None)

items: list[dict] = st.session_state["tb_items"]

# 保存先が無い場合は以降の保存を無効化（初回例外時）
if not persist_enabled:
    st.session_state["_tb_persist_disabled"] = True
persist_enabled = not st.session_state.get("_tb_persist_disabled", False)

c_sync, c_info = st.columns([1, 4])
if c_sync.button("🔄 同期（再読み込み）", width="stretch",
                 help="他の端末での変更を取り込みます。"):
    st.cache_data.clear()
    for k in list(st.session_state.keys()):
        if k.startswith(("bkt_", "spec_", "age_")) or k in ("tb_items",):
            del st.session_state[k]
    st.rerun()
total_all = sum(float(it.get("amount") or 0) for it in items)
placed = [it for it in items if it.get("bucket") in config.BUCKET_REPRESENTATIVE_AGE]
placed_total = sum(float(it.get("amount") or 0) for it in placed)
c_info.markdown(
    f"**登録 {len(items)} 件** / 合計 {yen(total_all)}　"
    f"　→　年代配置済み {len(placed)} 件（特別支出として計上: {yen(placed_total)}）"
)

if st.session_state.get("_tb_error"):
    st.error(f"保存に失敗しました: {st.session_state['_tb_error']}")

st.divider()


# ===========================================================================
#  カンバンボード
# ===========================================================================
columns = st.columns(len(config.TIME_BUCKETS), gap="small")

for col, bucket in zip(columns, config.TIME_BUCKETS):
    with col:
        color = BUCKET_COLORS.get(bucket, "#7F8C8D")
        bucket_items = [it for it in items if it.get("bucket") == bucket]
        subtotal = sum(float(it.get("amount") or 0) for it in bucket_items)
        rep = config.BUCKET_REPRESENTATIVE_AGE.get(bucket)
        rep_label = f"（{rep}歳に計上）" if rep else "（未計上）"
        st.markdown(
            f"<div class='tb-col-head' style='background:{color}'>"
            f"{bucket} <span class='tb-col-total'>· {len(bucket_items)}件 / "
            f"{yen(subtotal)}<br>{rep_label}</span></div>",
            unsafe_allow_html=True,
        )

        # --- 「未分類」列には新規追加フォームを置く -----------------------
        if bucket == config.TIME_BUCKETS[0]:
            with st.form(f"add_form_{bucket}", clear_on_submit=True):
                title = st.text_input("やりたいこと", placeholder="例: 家族でハワイ旅行")
                amount = st.number_input(
                    "予算（円）", min_value=0, value=1_000_000, step=100_000, format="%d"
                )
                submitted = st.form_submit_button(
                    "➕ 追加", width="stretch", disabled=not persist_enabled
                )
            if submitted:
                if not title.strip():
                    st.warning("やりたいことを入力してください。")
                else:
                    items.append({
                        "id": uuid.uuid4().hex[:8],
                        "title": title.strip(),
                        "amount": float(amount),
                        "bucket": config.TIME_BUCKETS[0],
                        "age": None,
                    })
                    if persist(items):
                        st.rerun()

        # --- カード群 ------------------------------------------------------
        if not bucket_items:
            st.caption("（カードはありません）")

        for it in bucket_items:
            iid = it["id"]
            with st.container(border=True):
                st.markdown(f"**{it['title']}**")
                st.markdown(f"💴 {yen(float(it.get('amount') or 0))}")

                # 年代の移動（ドラッグ&ドロップの代替）
                sel_key = f"bkt_{iid}"
                st.session_state.setdefault(sel_key, it["bucket"])
                new_bucket = st.selectbox(
                    "年代を移動", config.TIME_BUCKETS, key=sel_key,
                    label_visibility="collapsed",
                )
                if new_bucket != it["bucket"]:
                    it["bucket"] = new_bucket
                    if persist(items):
                        st.rerun()

                # 計上年齢の表示＋個別指定（任意）
                eff_age = it["age"] if it["age"] is not None else rep
                if it["bucket"] in config.BUCKET_REPRESENTATIVE_AGE:
                    st.caption(f"計上年齢: {eff_age}歳")
                with st.expander("⚙️ 実行年齢・削除"):
                    spec_key = f"spec_{iid}"
                    specify = st.checkbox(
                        "実行年齢を指定", value=it["age"] is not None, key=spec_key,
                        disabled=it["bucket"] not in config.BUCKET_REPRESENTATIVE_AGE,
                        help="未指定なら年代の中央の年齢に自動割り当て。",
                    )
                    if specify:
                        age_key = f"age_{iid}"
                        age_val = int(st.number_input(
                            "実行年齢", min_value=0, max_value=110,
                            value=int(it["age"] if it["age"] is not None else (rep or 40)),
                            step=1, key=age_key,
                        ))
                        if it["age"] != age_val:
                            it["age"] = age_val
                            if persist(items):
                                st.rerun()
                    else:
                        if it["age"] is not None:
                            it["age"] = None
                            if persist(items):
                                st.rerun()

                    if st.button("🗑 削除", key=f"del_{iid}",
                                 width="stretch", disabled=not persist_enabled):
                        st.session_state["tb_items"] = [
                            x for x in items if x["id"] != iid
                        ]
                        for k in (sel_key, f"spec_{iid}", f"age_{iid}"):
                            st.session_state.pop(k, None)
                        if persist(st.session_state["tb_items"]):
                            st.rerun()

st.divider()
st.caption(
    "💡 カード内のプルダウンで年代を変えると、その場でスプレッドシートへ保存され、"
    "ライフプランのグラフ・キャッシュフロー表にも自動反映されます。"
)

# 参考: この配置がライフプランでどう計上されるかのプレビュー
with st.expander("🔗 ライフプランへの計上プレビュー（特別支出）", expanded=False):
    events = lifeplan.special_events_from_buckets(items)
    if not events:
        st.caption("年代バケツに配置され、金額が入ったアイテムはまだありません。")
    else:
        import pandas as pd

        preview = pd.DataFrame(events).rename(
            columns={"label": "項目", "age": "計上年齢（夫）", "amount": "金額"}
        ).sort_values("計上年齢（夫）")
        st.dataframe(
            preview.style.format({"金額": "¥{:,.0f}"}),
            width="stretch", hide_index=True,
        )
