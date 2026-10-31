# -*- coding: utf-8 -*-
# @File     : us_market_trend.py
# @Project  : ai_quant_trade
# Function Description: 判断美股大盘当前处于多头趋势还是空头趋势，
#   追加保存每次检查的历史记录，并生成图表报告 (HTML)。
#
# 用法:
#   python us_market_trend.py              # 拉取数据、判断趋势、更新历史、生成报告
#   python us_market_trend.py --years 10   # 图表展示更长历史
#
# Licensed under the Apache License, Version 2.0

import argparse
import json
import os
from datetime import datetime, timezone

import pandas as pd
import requests

INDICES = {
    '^GSPC': '标普500',
    '^IXIC': '纳斯达克综合',
    '^DJI': '道琼斯工业',
    '^RUT': '罗素2000',
}
VIX = '^VIX'

BULL, BEAR, RANGE = '多头', '空头', '震荡'

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_CSV = os.path.join(HERE, 'history', 'trend_log.csv')
REPORT_HTML = os.path.join(HERE, 'history', 'us_market_trend.html')


def fetch_daily(symbol, years):
    """从 Yahoo Finance 拉取日线收盘价。"""
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + \
        requests.utils.quote(symbol)
    params = {'range': f'{years}y', 'interval': '1d'}
    resp = requests.get(url, params=params, timeout=30,
                        headers={'User-Agent': 'Mozilla/5.0'})
    resp.raise_for_status()
    res = resp.json()['chart']['result'][0]
    tz = res['meta'].get('exchangeTimezoneName', 'America/New_York')
    idx = pd.to_datetime(res['timestamp'], unit='s', utc=True) \
        .tz_convert(tz).normalize().tz_localize(None)
    close = pd.Series(res['indicators']['quote'][0]['close'], index=idx,
                      name='close', dtype='float64')
    close = close[~close.index.duplicated(keep='last')].dropna()
    return close


def score_trend(close):
    """
    多空评分 (-5 ~ +5)，每一项 +1 / -1：
      1. 收盘价 vs MA200        (长期趋势)
      2. MA50 vs MA200          (金叉 / 死叉)
      3. MA200 近 20 日斜率      (长期均线方向)
      4. 收盘价 vs MA50         (中期趋势)
      5. 距 52 周高点回撤: > -10% 记 +1, < -20% 记 -1 (技术性熊市), 其余 0
    总分 >= 3 为多头, <= -3 为空头, 其余为震荡。
    """
    df = close.to_frame()
    df['ma50'] = close.rolling(50).mean()
    df['ma200'] = close.rolling(200).mean()
    df['ma200_slope'] = df['ma200'].pct_change(20)
    df['high_52w'] = close.rolling(252, min_periods=1).max()
    df['drawdown'] = close / df['high_52w'] - 1

    def sign(cond):
        return cond.astype(int) * 2 - 1

    dd = df['drawdown']
    df['score'] = (
        sign(close > df['ma200'])
        + sign(df['ma50'] > df['ma200'])
        + sign(df['ma200_slope'] > 0)
        + sign(close > df['ma50'])
        + (dd > -0.10).astype(int) - (dd < -0.20).astype(int)
    )
    df = df.dropna(subset=['ma200', 'ma200_slope'])
    df['regime'] = df['score'].map(
        lambda s: BULL if s >= 3 else (BEAR if s <= -3 else RANGE))
    return df


def to_record(df, i, sym, name, checked_at):
    r = df.iloc[i]
    return {
        'date': df.index[i].strftime('%Y-%m-%d'),
        'symbol': sym,
        'name': name,
        'close': round(r['close'], 2),
        'ma50': round(r['ma50'], 2),
        'ma200': round(r['ma200'], 2),
        'ma200_slope_20d_pct': round(r['ma200_slope'] * 100, 2),
        'drawdown_52w_pct': round(r['drawdown'] * 100, 2),
        'score': int(r['score']),
        'regime': r['regime'],
        'checked_at': checked_at,
    }


def overall_regime(scores):
    avg = sum(scores) / len(scores)
    return avg, (BULL if avg >= 3 else (BEAR if avg <= -3 else RANGE))


def update_history(latest_rows):
    """追加本次检查结果；同一交易日同一指数只保留最新一次。"""
    new = pd.DataFrame(latest_rows)
    if os.path.exists(HISTORY_CSV):
        old = pd.read_csv(HISTORY_CSV, dtype={'date': str})
        new = pd.concat([old, new], ignore_index=True)
    new = new.drop_duplicates(subset=['date', 'symbol'], keep='last') \
        .sort_values(['date', 'symbol']).reset_index(drop=True)
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    new.to_csv(HISTORY_CSV, index=False)
    return new


def render_html(frames, history, vix, checked_at, overall):
    tpl_path = os.path.join(HERE, 'report_template.html')
    with open(tpl_path, encoding='utf-8') as f:
        tpl = f.read()
    series = {}
    for sym, df in frames.items():
        series[sym] = {
            'name': INDICES[sym],
            'date': df.index.strftime('%Y-%m-%d').tolist(),
            'close': df['close'].round(2).tolist(),
            'ma50': df['ma50'].round(2).tolist(),
            'ma200': df['ma200'].round(2).tolist(),
            'score': df['score'].astype(int).tolist(),
            'regime': df['regime'].tolist(),
        }
    payload = {
        'checked_at': checked_at,
        'overall': {'score': round(overall[0], 2), 'regime': overall[1]},
        'vix': vix,
        'series': series,
        'history': history.to_dict(orient='records'),
    }
    html = tpl.replace('/*__DATA__*/null',
                       json.dumps(payload, ensure_ascii=False))
    with open(REPORT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description='美股多空趋势检查')
    parser.add_argument('--years', type=int, default=5,
                        help='拉取并展示的历史年数 (需 >= 2 以计算 MA200)')
    parser.add_argument('--backfill', type=int, default=0,
                        help='用最近 N 个交易日的计算结果补写历史记录')
    args = parser.parse_args()

    checked_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    frames, rows, backfill_rows = {}, [], []
    for sym, name in INDICES.items():
        df = score_trend(fetch_daily(sym, args.years))
        frames[sym] = df
        for i in range(-max(args.backfill, 1), 0):
            row = to_record(df, i, sym, name,
                            checked_at if i == -1 else 'backfill')
            (rows if i == -1 else backfill_rows).append(row)

    vix_close = fetch_daily(VIX, 1)
    vix = {'date': vix_close.index[-1].strftime('%Y-%m-%d'),
           'close': round(float(vix_close.iloc[-1]), 2)}

    overall = overall_regime([r['score'] for r in rows])
    history = update_history(backfill_rows + rows)
    render_html(frames, history, vix, checked_at, overall)

    print(f'检查时间: {checked_at}')
    print(pd.DataFrame(rows)[['date', 'name', 'close', 'ma50', 'ma200',
                              'drawdown_52w_pct', 'score', 'regime']]
          .to_string(index=False))
    print(f'VIX: {vix["close"]} ({vix["date"]})')
    print(f'美股整体: {overall[1]} (平均评分 {overall[0]:+.2f} / 5)')
    print(f'历史记录: {HISTORY_CSV}')
    print(f'图表报告: {REPORT_HTML}')


if __name__ == '__main__':
    main()
