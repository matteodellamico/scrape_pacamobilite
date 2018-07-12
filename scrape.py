#!/usr/bin/env python3

import argparse
import datetime
import json
import re
from urllib import parse

import mechanicalsoup
import tabulate

STOP_REGEX = re.compile(r'^arret\d+$')
ROW_CLASS = re.compile(r'^row[01]$')
MINUTE = datetime.timedelta(minutes=1)


def parse_line(line, date, operator):

    browser = mechanicalsoup.StatefulBrowser()
    browser.open('https://www.pacamobilite.fr/index.asp')
    browser.follow_link("horaires_ligne")
    browser.select_form("form[id='searchByNumber']")
    browser["keywordsNumber"] = line
    soup = browser.get_current_page()
    operator_id = soup.find('option', text=operator)['value']
    browser["operator_id"] = operator_id
    browser.submit_selected()

    link_list = browser.get_current_page().find('ul', class_='lig').find('li')
    # lineno = link_list.find('span', class_='pictoLine')

    def parse_time(timestring):
        return datetime.datetime.strptime(timestring, '%H:%M')

    def parse_path(path_url):
        browser.open_relative(path_url)
        path_soup = browser.get_current_page()
        stops = [td.text for td in path_soup.find_all('td', id=STOP_REGEX)]
        rows = path_soup.find_all('tr', class_=ROW_CLASS)
        timetable = [[] for _ in rows]
        while True:
            assert len(stops) == len(rows), (len(stops), len(rows))
            for timerow, row in zip(timetable, rows):
                data = [parse_time(td.text) if td.text != '|' else None
                        for td in row.find_all('td', class_='horaire')]
                timerow.extend(data)
            next_link = path_soup.find('a', class_='laterHour')
            if next_link is None:
                break
            browser.open_relative(next_link['href'])
            path_soup = browser.get_current_page()
            rows = path_soup.find_all('tr', class_=ROW_CLASS)
        return stops, list(zip(*timetable))

    res = {}
    for a in link_list.find_all('a'):
        path = a.text
        link = a['href']
        url = parse.urlparse(link)
        query = parse.parse_qs(url.query)
        query['ladate'] = date
        query['lheure'] = query['laminute'] = '00'
        new_url = parse.urlunparse(url[:4]
                                   + (parse.urlencode(query, doseq=True),)
                                   + url[5:])
        res[path] = parse_path(new_url)
    return res


def build_table(linesdata, home, office):

    def time_s(time):
        res = time.strftime('%H:%M')
        if res.startswith('0'):
            res = res[1:]
        return res

    def filter_idx(stopnames, filtered):
        res = []
        for i, stop in enumerate(stopnames):
            try:
                delta = filtered[stop]
            except KeyError:
                continue
            else:
                res.append((i, stop, delta * MINUTE))
        return res

    def get_stops(idxlist, thetimes):
        for idx, stop, delta in idxlist:
            time = thetimes[idx]
            if time is not None:
                yield time, stop, delta

    home2office, office2home = set(), set()
    for line, linedata in linesdata:
        for direction, (stops, timetable) in linedata.items():
            idx_home = filter_idx(stops, home)
            idx_office = filter_idx(stops, office)

            if max(idx_home) < min(idx_office):
                trip = home2office
                idx_orig, idx_dest = idx_home, idx_office
            elif max(idx_office) < min(idx_home):
                trip = office2home
                idx_orig, idx_dest = idx_office, idx_home
            else:
                raise ValueError("trips that go from home to office and back or viceversa are not supported")

            for times in timetable:
                try:
                    orig_stop = max((time - delta, time, stop) for time, stop, delta in get_stops(idx_orig, times))
                    dest_stop = min((time + delta, time, stop) for time, stop, delta in get_stops(idx_dest, times))
                except ValueError:  # no stops at origin or destination
                    continue
                trip.add((orig_stop, dest_stop, line))

    home2office = sorted(home2office)
    office2home = sorted(office2home)

    def table(thetrip):
        headers = ["Trip", "", "", "Board at", "Line", "", "Descend at"]
        thetable = [
            ('{}-{}'.format(time_s(leave), time_s(arrive)),
             "({}')".format((arrive - leave).seconds // 60),
             time_s(board),
             orig,
             theline,
             time_s(descend),
             dest)
            for (leave, board, orig), (arrive, descend, dest), theline in thetrip
        ]
        return headers, thetable

    return table(home2office), table(office2home)


COLALIGN = ["right", "right", "right", "left", "right", "right", "left"]


def get_text(tables):
    return '\n\n'.join(tabulate.tabulate(table, header, colalign=COLALIGN) for header, table in tables)


def get_latex(tables):
    head = r'''
    \documentclass{scrartcl}
    \usepackage{booktabs}
    \usepackage[margin=0.5in]{geometry}
    \usepackage{longtable}
    \usepackage[table]{xcolor}
    \renewcommand{\familydefault}{\sfdefault}
    \renewenvironment{tabular}{\rowcolors{2}{gray!30}{white}\begin{longtable}}{\end{longtable}}
    \let\oldmidrule\midrule
    \renewcommand{\midrule}{\oldmidrule\endhead\bottomrule\endfoot\endlastfoot}
    \begin{document}
    '''

    mid = r'''
    \newpage
    '''
    
    tail = r'''
    \end{document}
    '''

    tables = [tabulate.tabulate(table, header, tablefmt='latex_booktabs', colalign=COLALIGN) for header, table in tables]

    return head + tables[0] + mid + tables[1] + tail


FORMATTING_FUNCTIONS = {
    'text': get_text,
    'latex': get_latex,
}


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('date')
    parser.add_argument('config')
    parser.add_argument('lines', nargs='+')
    parser.add_argument('--operator', default='Envibus')
    parser.add_argument('--format', choices=['text', 'latex'])
    args = parser.parse_args(args)

    with open(args.config) as f:
        config = json.load(f)

    linesdata = [(line, parse_line(line, args.date, args.operator)) for line in args.lines]

    tables = build_table(linesdata, config['home'], config['office'])

    print(FORMATTING_FUNCTIONS[args.format](tables))


if __name__ == '__main__':
    main()
