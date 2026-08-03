import json
from pathlib import Path

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px

# 1. Configuração Inicial da Página
st.set_page_config(
    page_title="Portfólio | Dashboard de FIIs",
    page_icon=":material/apartment:",
    layout="wide",
)

# Gradiente teal na sidebar (inspirado no modelo de referência do usuário)
st.html("""
<style>
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0F3D3E 0%, #14B8A6 100%) !important;
}
</style>
""")

ARQUIVO_CARTEIRA = Path(__file__).parent / "minha_carteira.json"


def carregar_carteira_salva():
    if ARQUIVO_CARTEIRA.exists():
        try:
            return json.loads(ARQUIVO_CARTEIRA.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def salvar_carteira(carteira):
    ARQUIVO_CARTEIRA.write_text(json.dumps(carteira, ensure_ascii=False, indent=2), encoding="utf-8")


def formatar_numero(valor, casas=2, sinal=False):
    """Formata no padrão brasileiro: ponto como separador de milhar, vírgula como decimal."""
    especificador = f"{{:{'+' if sinal else ''},.{casas}f}}"
    texto = especificador.format(valor)
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def formatar_moeda(valor):
    return f"R$ {formatar_numero(valor)}"


# 2. Função de Extração de Dados (Com Cache para não sobrecarregar a API)
@st.cache_data(ttl="1h")
def carregar_dados(tickers):
    lista_cotacoes = []
    lista_dividendos = []

    for ticker in tickers:
        fundo = yf.Ticker(f"{ticker}.SA")

        # Histórico de Cotações (1 ano)
        df_hist = fundo.history(period="1y")
        if not df_hist.empty:
            df_hist = df_hist.reset_index()
            df_hist['Ticker'] = ticker
            lista_cotacoes.append(df_hist[['Date', 'Close', 'Ticker']])

        # Histórico de Dividendos (últimos 13 meses, para acompanhar o período das cotações)
        s_div = fundo.dividends
        if not s_div.empty:
            data_limite = s_div.index.max() - pd.DateOffset(months=13)
            s_div = s_div[s_div.index >= data_limite]
            df_div = s_div.to_frame(name='Valor_Dividendo').reset_index()
            df_div['Ticker'] = ticker
            lista_dividendos.append(df_div)

    # Tratamento e concatenação
    df_cotacoes = pd.concat(lista_cotacoes).rename(columns={'Date': 'Data', 'Close': 'Preco'})
    df_cotacoes['Data'] = pd.to_datetime(df_cotacoes['Data']).dt.tz_localize(None)

    df_dividendos = pd.concat(lista_dividendos).rename(columns={'Date': 'Data'})
    df_dividendos['Data'] = pd.to_datetime(df_dividendos['Data']).dt.tz_localize(None)

    return df_cotacoes, df_dividendos


# 3. Função de Cálculo de KPIs
@st.cache_data
def calcular_kpis(df_cotacoes, df_dividendos):
    # Preço mais recente
    df_preco = df_cotacoes.sort_values('Data').drop_duplicates('Ticker', keep='last')[['Ticker', 'Preco']]

    # Variação de preço no período (primeiro vs. último preço disponível)
    df_variacao = df_cotacoes.sort_values('Data').groupby('Ticker')['Preco'].agg(
        Preco_Inicial='first', Preco_Final='last'
    ).reset_index()
    df_variacao['Variacao_12M'] = (df_variacao['Preco_Final'] / df_variacao['Preco_Inicial'] - 1) * 100

    # Soma dos dividendos dos últimos 12 meses
    data_corte = df_dividendos['Data'].max() - pd.DateOffset(months=12)
    df_div_12m = df_dividendos[df_dividendos['Data'] >= data_corte]
    df_soma = df_div_12m.groupby('Ticker')['Valor_Dividendo'].sum().reset_index()

    # Cruzamento para cálculo do DY
    df_kpi = pd.merge(df_preco, df_soma, on='Ticker', how='left').fillna(0)
    df_kpi = pd.merge(df_kpi, df_variacao[['Ticker', 'Variacao_12M']], on='Ticker', how='left')
    df_kpi['DY_12M'] = (df_kpi['Valor_Dividendo'] / df_kpi['Preco']) * 100
    return df_kpi


# --- CONSTRUÇÃO DA INTERFACE VISUAL ---
st.title(":material/apartment: Painel de acompanhamento de fundos imobiliários")
st.caption("Projeto de portfólio desenvolvido para análise de rendimentos e cotações de FIIs.")

# Sidebar - Menu Lateral
with st.sidebar:
    st.header(":material/tune: Filtros do painel")
    tickers_padrao = ['MXRF11', 'MCCI11', 'XPSF11', 'GARE11']
    ativos_selecionados = st.multiselect(
        "Selecione os FIIs",
        tickers_padrao,
        default=tickers_padrao,
        accept_new_options=True,
        placeholder="Escolha ou digite um novo ticker (ex: HGLG11)",
        help="Não achou o fundo na lista? Digite o ticker e pressione Enter para adicioná-lo.",
    )
    ativos_selecionados = [ticker.strip().upper() for ticker in ativos_selecionados]

    carteira_salva = carregar_carteira_salva()

    cotas_por_fundo = {}
    if ativos_selecionados:
        st.header(":material/wallet: Minha carteira")
        st.caption("Informe quantas cotas você possui de cada fundo para estimar sua renda mensal.")
        for ticker in ativos_selecionados:
            cotas_por_fundo[ticker] = st.number_input(
                f"Cotas de {ticker}",
                min_value=0,
                value=int(carteira_salva.get(ticker, 0)),
                step=1,
                key=f"cotas_{ticker}",
            )

        if any(cotas_por_fundo[t] != carteira_salva.get(t, 0) for t in cotas_por_fundo):
            salvar_carteira({**carteira_salva, **cotas_por_fundo})

        st.caption(":material/check_circle: Cotas salvas automaticamente neste computador.")

if not ativos_selecionados:
    st.warning("Selecione pelo menos um fundo imobiliário no menu lateral.", icon=":material/warning:")
    st.stop()

# Chama as funções (se os dados já estiverem em cache, carrega instantaneamente)
df_cotacoes, df_dividendos = carregar_dados(ativos_selecionados)
df_kpi = calcular_kpis(df_cotacoes, df_dividendos)
df_kpi['Cotas'] = df_kpi['Ticker'].map(cotas_por_fundo).fillna(0)

df_div_mensal = (
    df_dividendos.assign(Mes=df_dividendos['Data'].dt.to_period('M').dt.to_timestamp())
    .groupby(['Mes', 'Ticker'])['Valor_Dividendo'].sum()
    .reset_index()
)

# Visão 1: Indicadores consolidados da carteira
st.subheader(":material/pie_chart: Visão consolidada da carteira")

melhor_dy = df_kpi.loc[df_kpi['DY_12M'].idxmax()]
melhor_valorizacao = df_kpi.loc[df_kpi['Variacao_12M'].idxmax()]

with st.container(horizontal=True):
    st.metric(
        "Ativos monitorados",
        f"{len(ativos_selecionados)}",
        border=True,
    )
    st.metric(
        "DY médio da carteira",
        f"{formatar_numero(df_kpi['DY_12M'].mean())}%",
        border=True,
    )
    st.metric(
        "Dividendos 12M (soma/cota)",
        formatar_moeda(df_kpi['Valor_Dividendo'].sum()),
        border=True,
    )
    st.metric(
        "Maior DY 12M",
        melhor_dy['Ticker'],
        delta=f"{formatar_numero(melhor_dy['DY_12M'])}%",
        border=True,
    )
    st.metric(
        "Melhor valorização",
        melhor_valorizacao['Ticker'],
        delta=f"{formatar_numero(melhor_valorizacao['Variacao_12M'])}%",
        border=True,
    )

st.space("large")

# Visão 2: Resumo por fundo (KPIs individuais)
st.subheader(":material/apartment: Detalhamento por fundo")

with st.container(horizontal=True):
    for ticker in ativos_selecionados:
        dados_fundo = df_kpi[df_kpi['Ticker'] == ticker].iloc[0]
        historico_preco = (
            df_cotacoes[df_cotacoes['Ticker'] == ticker]
            .sort_values('Data')['Preco']
            .tolist()
        )

        with st.container(border=True):
            st.metric(
                label=ticker,
                value=formatar_moeda(dados_fundo['Preco']),
                delta=f"{formatar_numero(dados_fundo['Variacao_12M'], sinal=True)}% (12M)",
                chart_data=historico_preco,
                chart_type="line",
            )
            st.caption(f"DY 12M: {formatar_numero(dados_fundo['DY_12M'])}% · Proventos: {formatar_moeda(dados_fundo['Valor_Dividendo'])}/cota")
            if dados_fundo['Cotas'] > 0:
                renda_media = dados_fundo['Valor_Dividendo'] / 12 * dados_fundo['Cotas']
                st.caption(f"Renda média/mês: {formatar_moeda(renda_media)} ({dados_fundo['Cotas']:.0f} cotas)")

st.space("large")

# Visão 3: Rendimento estimado com as cotas informadas
total_cotas = sum(cotas_por_fundo.values())

if total_cotas > 0:
    st.subheader(":material/savings: Rendimento estimado com suas cotas")

    df_kpi['Patrimonio'] = df_kpi['Preco'] * df_kpi['Cotas']
    df_kpi['Renda_Mensal_Media'] = df_kpi['Valor_Dividendo'] / 12 * df_kpi['Cotas']

    with st.container(horizontal=True):
        st.metric("Patrimônio investido", formatar_moeda(df_kpi['Patrimonio'].sum()), border=True)
        st.metric("Renda mensal média estimada", formatar_moeda(df_kpi['Renda_Mensal_Media'].sum()), border=True)
        st.metric(
            "Renda anual estimada (12M)",
            formatar_moeda((df_kpi['Valor_Dividendo'] * df_kpi['Cotas']).sum()),
            border=True,
        )

    st.space("large")

    with st.container(border=True):
        st.subheader(":material/monitoring: Renda mensal recebida por fundo (R$)")
        df_renda_mensal = df_div_mensal.merge(df_kpi[['Ticker', 'Cotas']], on='Ticker', how='left')
        df_renda_mensal['Renda'] = df_renda_mensal['Valor_Dividendo'] * df_renda_mensal['Cotas']
        totais_mensais = df_renda_mensal.groupby('Mes')['Renda'].sum().reset_index()

        fig_renda = px.bar(df_renda_mensal, x='Mes', y='Renda', color='Ticker', barmode='stack')
        fig_renda.add_scatter(
            x=totais_mensais['Mes'],
            y=totais_mensais['Renda'],
            mode='text',
            text=[formatar_moeda(valor) for valor in totais_mensais['Renda']],
            textposition='top center',
            showlegend=False,
            hoverinfo='skip',
        )
        fig_renda.update_layout(
            yaxis_title="Renda (R$)",
            yaxis_range=[0, totais_mensais['Renda'].max() * 1.2],
            bargap=0.15,
            xaxis_title=None,
            legend_title_text="",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=40, b=10),
            height=320,
            hovermode="x unified",
            separators=",.",
        )
        fig_renda.update_xaxes(dtick="M1", tickformat="%b/%y")
        st.plotly_chart(fig_renda, width="stretch")

    st.space("large")
else:
    st.caption("Informe a quantidade de cotas na barra lateral para estimar sua renda mensal.")
    st.space("large")

# Visão 4: Gráficos (Plotly) — layout limpo, sem poluição visual
layout_grafico = dict(
    xaxis_title=None,
    legend_title_text="",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=10, r=10, t=40, b=10),
    height=380,
    hovermode="x unified",
    separators=",.",
)

col1, col2 = st.columns(2)

with col1:
    with st.container(border=True):
        st.subheader(":material/show_chart: Rentabilidade comparada (base 100)")
        df_rentabilidade = df_cotacoes.sort_values('Data').copy()
        df_rentabilidade['Rentabilidade'] = df_rentabilidade.groupby('Ticker')['Preco'].transform(
            lambda serie: serie / serie.iloc[0] * 100
        )
        fig_cotacoes = px.line(df_rentabilidade, x='Data', y='Rentabilidade', color='Ticker')
        fig_cotacoes.update_layout(yaxis_title="Rentabilidade (base 100)", **layout_grafico)
        st.plotly_chart(fig_cotacoes, width="stretch")

with col2:
    with st.container(border=True):
        st.subheader(":material/payments: Dividendos mensais por fundo")
        fig_dividendos = px.bar(df_div_mensal, x='Mes', y='Valor_Dividendo', color='Ticker', barmode='group')
        fig_dividendos.update_layout(yaxis_title="Dividendos (R$/cota)", bargap=0.15, **layout_grafico)
        fig_dividendos.update_xaxes(dtick="M1", tickformat="%b/%y")
        st.plotly_chart(fig_dividendos, width="stretch")
