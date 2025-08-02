import os
import io
import re
import zipfile
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
import streamlit as st

base_url = 'https://loadsensing.wocs3.com'
urls = [f'{base_url}/27920/dataserver/node/view/{nid}' for nid in [1006, 1007, 1008, 1010, 1011, 1012]]

def coletar_links():
    auth = (
        st.secrets["GATEWAY_USERNAME"],
        st.secrets["GATEWAY_PASSWORD"]
    )
    all_file_links = {}
    for url in urls:
        try:
            r = requests.get(url, auth=auth)
            soup = BeautifulSoup(r.text, 'html.parser')
            node_id = re.search(r'/view/(\d+)$', url).group(1)
            file_links = [a['href'] for a in soup.find_all('a', href=True) if a['href'].endswith(('.csv', '.zip'))]
            if file_links:
                all_file_links[node_id] = file_links
        except Exception as e:
            print(f"Erro em {url}: {e}")
    return all_file_links

def baixar_arquivos(all_file_links):
    auth = (
        st.secrets["GATEWAY_USERNAME"],
        st.secrets["GATEWAY_PASSWORD"]
    )
    hoje = datetime.now()
    limite_data = hoje.replace(day=1)
    meses = [(limite_data.year, limite_data.month)]
    for i in range(1, 3):
        m = limite_data.month - i
        y = limite_data.year
        if m <= 0:
            y -= 1
            m += 12
        meses.append((y, m))

    downloaded_files = {}
    for node_id, links in all_file_links.items():
        downloaded_files[node_id] = []
        for link in links:
            filename = link.split('/')[-1]
            if 'current' in filename.lower():
                baixar = True
            else:
                try:
                    partes = filename.split('-')
                    ano = int(partes[-2])
                    mes = int(partes[-1].split('.')[0])
                    baixar = (ano, mes) in meses
                except:
                    continue
            if not baixar:
                continue
            full_url = base_url + link
            response = requests.get(full_url, auth=auth)
            if response.status_code == 200:
                filepath = f"{node_id}_{filename}"
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                downloaded_files[node_id].append(filepath)
    return downloaded_files

def processar_arquivos(downloaded_files):
    all_dataframes = {}
    for node_id, files in downloaded_files.items():
        dfs_node = []
        for fp in files:
            if fp.endswith('.csv'):
                try:
                    df = pd.read_csv(fp, skiprows=9)
                    dfs_node.append(df)
                except:
                    continue
            elif fp.endswith('.zip'):
                try:
                    with zipfile.ZipFile(fp, 'r') as zf:
                        for fn in zf.namelist():
                            if fn.endswith('.csv'):
                                with zf.open(fn) as f:
                                    df = pd.read_csv(io.TextIOWrapper(f, 'utf-8'), skiprows=9)
                                    dfs_node.append(df)
                except:
                    continue
        if dfs_node:
            df_concat = pd.concat(dfs_node, ignore_index=True)
            all_dataframes[node_id] = df_concat
    return all_dataframes

def calcular_correlacao_mensal(todos_nos):
    correlacoes = []
    node_ids = {re.search(r'-(\d+)-', c).group(1) for c in todos_nos.columns if re.search(r'-(\d+)-', c)}
    for nid in node_ids:
        p_col = f'p-{nid}-Ch1'
        f_col = f'freqInHz-{nid}-VW-Ch1'
        if p_col in todos_nos.columns and f_col in todos_nos.columns:
            df_node = todos_nos[['Month', p_col, f_col]].dropna()
            grouped = df_node.groupby('Month')
            for m, df_group in grouped:
                if len(df_group) > 2:
                    corr = df_group[p_col].corr(df_group[f_col])
                    correlacoes.append({
                        'Month': str(m),
                        'Node_ID': nid,
                        'Correlation': corr
                    })
    return pd.DataFrame(correlacoes)

def analisar_e_salvar(all_dataframes):
    first_node = list(all_dataframes.keys())[0]
    todos_nos = all_dataframes[first_node].copy()
    for node_id, df in all_dataframes.items():
        if node_id != first_node and 'Date-and-time' in df.columns:
            todos_nos = pd.merge(todos_nos, df, on='Date-and-time', how='outer', suffixes=('', f'_{node_id}'))

    todos_nos['Date-and-time'] = pd.to_datetime(todos_nos['Date-and-time'], errors='coerce')
    todos_nos.dropna(subset=['Date-and-time'], inplace=True)
    todos_nos['Date'] = todos_nos['Date-and-time'].dt.date
    todos_nos['Time_Rounded'] = todos_nos['Date-and-time'].dt.round('h').dt.time
    todos_nos['Month'] = todos_nos['Date-and-time'].dt.to_period('M')

    df_cleaned = todos_nos.copy()
    df_cleaned.drop_duplicates(subset=['Date', 'Time_Rounded'], inplace=True)
    p_cols = [c for c in df_cleaned.columns if c.startswith('p-')]
    df_selected = df_cleaned[['Date-and-time', 'Time_Rounded'] + p_cols].copy()
    melted = df
