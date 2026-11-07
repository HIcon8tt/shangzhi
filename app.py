import os
import pandas as pd
import folium
import streamlit as st

st.set_page_config(page_title="商智选址 v1.3", layout="wide")

@st.cache_data
def load_data():
    shop = pd.read_csv("西安餐饮_清洗版.csv")
    dem = pd.read_csv("需求侧_清洗版.csv")
    park = pd.DataFrame()
    if os.path.exists("公园_清洗版.csv"):
        park = pd.read_csv("公园_清洗版.csv")
    return shop, dem, park

shop, dem, park = load_data()

shop["网格"] = shop["经度"].round(2).astype(str) + "," + shop["纬度"].round(2).astype(str)
pivot_shop = shop.pivot_table(index="网格", columns="业态", values="店名",
                              aggfunc="count", fill_value=0)
pivot_dem = dem.pivot_table(index="网格", columns="类型", values="名称",
                            aggfunc="count", fill_value=0).reindex(pivot_shop.index).fillna(0)
if not park.empty:
    pivot_dem["公园"] = park.groupby("网格")["名称"].count().reindex(pivot_shop.index).fillna(0)

st.sidebar.title("商智选址 v1.3")
target = st.sidebar.selectbox("目标业态", pivot_shop.columns.tolist())
mode = st.sidebar.radio("评分模式",
                        ["新消费机会", "市场缺口（高普及业态）"])
comp = st.sidebar.multiselect("互补业态（可改）",
                              pivot_shop.columns.tolist(),
                              default=[c for c in ["甜品", "烘焙糕点", "茶饮"] if c in pivot_shop.columns])
alive_n = st.sidebar.number_input("存活门店数阈值", min_value=1, value=2)

alive = pivot_shop[pivot_shop[target] >= alive_n].index
weights = {}
for col in ["住宅", "办公", "学校", "别墅", "公园"]:
    if col in pivot_dem.columns and pivot_dem[col].mean() > 0:
        weights[col] = pivot_dem.loc[alive, col].mean() / pivot_dem[col].mean()
w = {k: round(v / weights["住宅"], 2) for k, v in weights.items()}
st.sidebar.write("自校准权重（住宅=1）：", w)
st.sidebar.write(f"存活格：{len(alive)} 个")

for c in comp + [target]:
    if c not in pivot_shop.columns:
        pivot_shop[c] = 0

flagged = set()
for cat in pivot_shop.columns:
    total = pivot_shop[cat].sum()
    if total > 0:
        flagged |= set(pivot_shop[(pivot_shop[cat] >= 15)
                                  & (pivot_shop[cat] / total >= 0.01)].index)

demand = sum(pivot_dem[col] * w[col] for col in w) / 10

# 两种评分模式：互补竞争逻辑 / 市场缺口逻辑
if mode == "新消费机会":
    supply = pivot_shop[comp].sum(axis=1) * 2 - pivot_shop[target] * 3
    r_show = None
else:
    # 缺口模式：r 由数据自动校准（该业态 >=5 家的存活格里 门店数/需求分 的中位数）
    alive_gap = pivot_shop[pivot_shop[target] >= 5].index
    sub = pd.DataFrame({"stores": pivot_shop[target],
                        "demand": demand}).loc[alive_gap]
    sub = sub[sub["demand"] > 0]
    r = (sub["stores"] / sub["demand"]).median()
    if pd.isna(r):
        r = 1.0
    supply = demand * r - pivot_shop[target]
    r_show = round(float(r), 2)
    st.sidebar.write(f"缺口校准系数 r：{r_show}（需求1分≈{r_show}家店）")

score = pd.DataFrame({"供给机会分": supply.round(1), "需求分": demand.round(1)}).fillna(0)
score["综合分"] = (score["供给机会分"] + score["需求分"]).round(2)
top = score[~score.index.isin(flagged)].sort_values("综合分", ascending=False).head(30)

st.title(f"{target} 选址评分（v1.3 · {mode}）")
st.caption(f"数据：餐饮 {len(shop)} 条｜需求侧 {len(dem)} 条｜主题区已剔除 {len(flagged)} 格")

left, right = st.columns([1, 1.6])

with left:
    st.subheader("TOP30 候选网格（点击行看明细）")
    show = top.reset_index().rename(columns={"index": "网格"})
    for col in ["住宅", "办公", "学校"]:
        show[col] = pivot_dem[col].reindex(show["网格"]).values
    event = st.dataframe(show, use_container_width=True, height=420,
                         on_select="rerun", selection_mode="single-row")
    st.download_button("下载榜单 CSV",
                       show.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                       file_name=f"{target}_候选网格_v13.csv")
    rows = event.selection.rows
    if rows:
        grid = show.iloc[rows[0]]["网格"]
        st.markdown(f"**网格 {grid} 内门店明细**")
        detail = shop[shop["网格"] == grid][["店名", "业态", "地址"]]
        st.dataframe(detail, use_container_width=True, height=280)

with right:
    st.subheader("候选位置地图")
    m = folium.Map(location=[34.26, 108.94], zoom_start=11,
                   tiles="https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
                   attr="gaode")
    pts = shop[shop["业态"] == target]
    if len(pts) > 3000:
        pts = pts.sample(3000, random_state=42)
    for _, r2 in pts.iterrows():
        folium.CircleMarker([r2["纬度"], r2["经度"]], radius=2, color="#4C72B0",
                            fill=True, fill_opacity=0.5,
                            popup=str(r2["店名"])).add_to(m)
    for rank, grid in enumerate(top.index[:20], 1):
        lon, lat = map(float, grid.split(","))
        folium.CircleMarker([lat, lon], radius=9, color="red", fill=True,
                            popup=f"第{rank}名 {grid}<br>综合分 {top.loc[grid, '综合分']}").add_to(m)
        folium.Marker([lat, lon], icon=folium.DivIcon(
            html=f'<div style="font-size:11px;color:white;background:red;'
                 f'border-radius:50%;width:18px;height:18px;'
                 f'text-align:center;line-height:18px;">{rank}</div>')).add_to(m)
    st.components.v1.html(m._repr_html_(), height=560)