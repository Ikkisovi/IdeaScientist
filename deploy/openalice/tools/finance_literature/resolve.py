#!/usr/bin/env python3
"""Find non-SSRN public locations for unavailable papers, retaining discovery evidence."""
from difflib import SequenceMatcher
import json
from pathlib import Path
import sqlite3
import time
import urllib.parse

from collect import fetch, normalized, put, soup


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('db', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(f'file:{args.db}?mode=ro&immutable=1', uri=True) as db:
        rows = [json.loads(m) for m, in db.execute('SELECT meta_json FROM papers WHERE full_text=""')]
    manual = {
        'ssrn-2731886': ['https://escholarship.org/uc/item/4hn4t174'],
        'ssrn-2249314': ['https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.pdf'],
        'ssrn-3002503': ['https://ideas.repec.org/p/fau/wpaper/wp2017_18.html'],
        'ssrn-2757113': ['https://research.aalto.fi/en/publications/quantifying-backtest-overfitting-in-alternative-beta-strategies/'],
        'ssrn-2044725': ['https://www.econstor.eu/bitstream/10419/87470/1/12-042.pdf'],
        'ssrn-4082978': ['https://www.imf.org/-/media/files/publications/wp/2022/english/wpiea2022052-print-pdf.pdf'],
        'ssrn-3100811': ['https://hal.science/hal-03275900/document'],
        'ssrn-3894861': ['https://iris.imtlucca.it/retrieve/handle/20.500.11771/19679/20740/Longo%2CRiccaboni%2CRungi.pdf'],
        'ssrn-2610808': ['https://business.columbia.edu/sites/default/files-efs/pubfiles/25463/fluid-ms-2015.pdf'],
        'ssrn-7147361': ['https://arxiv.org/pdf/2607.28323'],
        'ssrn-5251604': ['https://assets-eu.researchsquare.com/files/rs-6917884/v1_covered_b071bc36-26a8-43bb-93ec-5dfaa5b012e5.pdf?c=1750308817'],
        'ssrn-3044740': ['https://journals.sagepub.com/doi/pdf/10.3233/AF-180231'],
        'ssrn-3950568': ['https://onlinelibrary.wiley.com/doi/10.1111/joes.12532'],
        'ssrn-4117882': ['https://aneuhierl.github.io/'],
        'ssrn-5346842': ['https://bryankellyacademic.org/'],
        'ssrn-6105327': ['https://www.lukavulicevic.com/'],
    }
    output = []
    audit = []
    for row in rows:
        title = soup(row['title'].encode()).get_text(' ', strip=True)
        urls = list(manual.get(row['key'], []))
        response = None
        error = ''
        url = 'https://api.openalex.org/works?' + urllib.parse.urlencode(
            {'filter': 'title.search:' + title, 'per-page': 5})
        try:
            data, _, _ = fetch(url)
            response = json.loads(data)
            put(args.out / (row['key'] + '-openalex.json'), response)
            for work in response.get('results', []):
                similarity = SequenceMatcher(None, normalized(title), normalized(work.get('title', ''))).ratio()
                if similarity < .94:
                    continue
                for location in work.get('locations', []):
                    for field in ('pdf_url', 'landing_page_url'):
                        link = location.get(field)
                        if link and 'ssrn.com' not in link.lower():
                            urls.append(link)
        except Exception as exc:
            error = str(exc)
        # Author pages and repository records can contain a direct file or download link.
        discovered = []
        for landing_index, landing in enumerate(dict.fromkeys(urls[:4])):
            if '.pdf' in landing.lower() or landing.endswith('/document'):
                continue
            try:
                data, final, kind = fetch(landing)
                if data.startswith(b'%PDF'):
                    discovered.append(landing)
                    continue
                (args.out / (row['key'] + '-' + str(landing_index) + '-landing.html')).write_bytes(data)
                page = soup(data)
                for a in page.select('a[href]'):
                    href = urllib.parse.urljoin(final, a['href'])
                    context = (a.find_parent('li') or a.find_parent('p') or a.parent).get_text(' ', strip=True)
                    if ('ssrn.com' not in href and ('.pdf' in href.lower() or '/document' in href)
                            and (len(urls) == 1 or SequenceMatcher(None, normalized(title),
                            normalized(a.get_text(' ', strip=True))).ratio() > .7
                            or title.lower() in context.lower())):
                        discovered.append(href)
            except Exception as exc:
                audit.append({'key': row['key'], 'landing': landing, 'error': str(exc)})
        urls = list(dict.fromkeys(discovered + urls))
        audit.append({'key': row['key'], 'title': title, 'discovered_urls': urls, 'openalex_error': error})
        for i, link in enumerate(urls[:6]):
            source = 'author' if 'ssrn.com' not in link else 'ssrn'
            author = row.get('authors', '')
            if 'Paper statistics' in author or 'job opening' in author:
                author = ''
            output.append({'source': source, 'key': row['key'] + '-mirror-' + str(i),
                'title': title, 'authors': author, 'origin_key': row['key'], 'origin_url': row['url'],
                'url': link, 'pdf_urls': [link] if '.pdf' in link.lower() or link.endswith('/document') else [],
                'mirror_discovery': 'non-SSRN location; title and author identity require body checks'})
        print(row['key'],len(urls),'candidate locations',flush=True)
        time.sleep(.1)
    put(args.out / 'audit.json', audit)
    put(args.out / 'seeds.json', output)
    print(args.out,flush=True)


if __name__ == '__main__':
    main()
