#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iPhone 到店取货库存查询
读取 config.json，调用 Apple 官网取货接口，把结果写入 docs/data.json。
用法: python3 check.py
可选: 设置环境变量 BARK_KEY，有货时推送到 iPhone (需先安装 Bark App)。
"""
import http.cookiejar
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.parse

BASE = 'https://www.apple.com.cn'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def fetch(url, headers, opener, timeout=30):
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def main():
    with open('config.json', encoding='utf-8') as f:
        cfg = json.load(f)

    parts = []
    part_info = {}
    for m in cfg['models']:
        for p in m['parts']:
            if p['part'] not in part_info:
                parts.append(p['part'])
                part_info[p['part']] = {
                    'model': m['name'], 'capacity': p['capacity'],
                    'color': p['color'], 'price': p['price'],
                }

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base_headers = {'User-Agent': UA}

    # 先访问一次购买页拿到 cookie，模拟真实用户，免得被拦
    try:
        fetch(BASE + '/shop/buy-iphone/iphone-18-pro', base_headers, opener)
    except Exception as e:
        print('预热失败(继续尝试):', e, file=sys.stderr)
    time.sleep(2)

    results = []
    # 苹果单次请求最多返回约 20 个型号的结果，分批查再合并
    BATCH = 15
    batches = [parts[i:i + BATCH] for i in range(0, len(parts), BATCH)]
    headers = dict(base_headers)
    headers.update({
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': BASE + '/shop/buy-iphone/iphone-18-pro',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
    })
    for s in cfg['stores']:
        num = s['number']
        entry = {
            'store_number': num,
            'store_name': s['name'],
            'city': s.get('city', ''),
            'parts': {},
            'error': None,
        }
        try:
            for bi, batch in enumerate(batches):
                query = [('pl', 'true'), ('mts.0', 'regular'), ('store', num)]
                query += [(f'parts.{i}', p) for i, p in enumerate(batch)]
                url = BASE + '/shop/retail/pickup-message?' + urllib.parse.urlencode(query)
                raw = fetch(url, headers, opener)
                data = json.loads(raw)
                body = data.get('body', {})
                if body.get('errorMessage'):
                    raise RuntimeError(str(body['errorMessage'])[:200])
                stores = body.get('stores') or \
                    body.get('content', {}).get('pickupMessage', {}).get('stores', [])
                st = next((x for x in stores if x.get('storeNumber') == num), None)
                if not st:
                    raise RuntimeError('接口没有返回该门店的数据')
                pa = st.get('partsAvailability', {}) or {}
                for p in batch:
                    info = pa.get(p, {})
                    entry['parts'][p] = {
                        'display': info.get('pickupDisplay', 'unknown'),
                        'quote': info.get('pickupSearchQuote', ''),
                    }
                entry['store_name'] = st.get('storeName', entry['store_name'])
                time.sleep(2)
            print(f'{num} {entry["store_name"]}: 查询成功')
        except Exception as e:
            entry['error'] = str(e)[:200]
            print(f'{num} 查询失败: {e}', file=sys.stderr)
        results.append(entry)
        time.sleep(3)  # 门店之间停 3 秒，别把苹果问烦了

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    out = {
        'updated_at': now.isoformat(timespec='seconds'),
        'updated_at_cn': now.strftime('%m月%d日 %H:%M'),
        'results': results,
    }
    os.makedirs('docs', exist_ok=True)
    with open('docs/data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    # 网页还需要 config.json 里的机型对照表，一起复制过去
    with open('config.json', encoding='utf-8') as f:
        cfg_text = f.read()
    with open('docs/config.json', 'w', encoding='utf-8') as f:
        f.write(cfg_text)
    print('已写入 docs/data.json')

    # Bark 推送(可选): 有货才推，没货不打扰
    bark_key = os.environ.get('BARK_KEY', '').strip()
    if bark_key:
        hits = []
        for r in results:
            for p, st in r['parts'].items():
                if st.get('display') == 'available':
                    i = part_info[p]
                    hits.append(f"{i['model']} {i['capacity']} {i['color']} @ {r['store_name']}")
        if hits:
            title = urllib.parse.quote('iPhone 到店有货了')
            body_q = urllib.parse.quote('\n'.join(hits[:12]), safe='')
            try:
                urllib.request.urlopen(
                    f'https://api.day.app/{bark_key}/{title}/{body_q}',
                    timeout=15).read()
                print(f'Bark 推送已发送 ({len(hits)} 条有货)')
            except Exception as e:
                print('Bark 推送失败:', e, file=sys.stderr)


if __name__ == '__main__':
    main()
