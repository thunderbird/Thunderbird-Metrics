#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 pontoon.py

import atexit
import base64
import csv
import io
import locale
import logging
import operator
import os
import platform
import sys
from datetime import datetime, timezone
from itertools import starmap
from json.decoder import JSONDecodeError

import matplotlib.pyplot as plt
import requests
import urllib3
from requests.exceptions import HTTPError, RequestException

locale.setlocale(locale.LC_ALL, "")

session = requests.Session()
session.headers["User-Agent"] = (
	f"Thunderbird Metrics ({session.headers['User-Agent']} {platform.python_implementation()}/{platform.python_version()})"
)
session.mount("https://", requests.adapters.HTTPAdapter(max_retries=urllib3.util.Retry(3, backoff_factor=1)))
atexit.register(session.close)

PONTOON_BASE_URL = "https://pontoon.mozilla.org/"
PONTOON_API_URL = f"{PONTOON_BASE_URL}api/v2/"

FF_PROJECTS = ("firefox", "firefox-for-android", "firefox-for-ios")
PROJECTS = ("thunderbird", "thunderbirdnet")

LIMIT = 1000


def output_markdown_table(rows, header):
	rows.insert(0, header)
	# rows = [[MARKDOWN_ESCAPE.sub(r"\\\1", col) for col in row] for row in rows]
	lens = [max(*map(len, col), 2) for col in zip(*rows)]
	rows.insert(1, ["-" * alen for alen in lens])
	aformat = " | ".join(f"{{:<{alen}}}" for alen in lens)

	print("\n".join(starmap(aformat.format, rows)))


def fig_to_data_uri(fig):
	with io.BytesIO() as buf:
		fig.savefig(buf, format="svg", bbox_inches="tight")
		plt.close(fig)

		# "data:image/svg+xml," + quote(buf.getvalue())
		return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def output_stacked_bar_graph(adir, labels, stacks, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(16, 6))

	ax.margins(0.01)
	ax.grid()

	cum = [0] * len(labels)

	for name, values in stacks.items():
		ax.bar(labels, values, bottom=cum, label=name)
		for i in range(len(cum)):
			cum[i] += values[i]

	ax.ticklabel_format(axis="y", useLocale=True)
	ax.tick_params("x", rotation=90)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def get_locales():
	locales = []
	page = 1

	while True:
		logging.info("\tPage %s (%s)", page, len(locales))

		try:
			r = session.get(
				f"{PONTOON_API_URL}locales/",
				params={"page": page, "page_size": LIMIT, "fields": "code,name,population"},
				timeout=30,
			)
			r.raise_for_status()
			data = r.json()
		except HTTPError as e:
			logging.critical("%s\n%r", e, r.text)
			sys.exit(1)
		except (RequestException, JSONDecodeError) as e:
			logging.critical("%s: %s", type(e).__name__, e)
			sys.exit(1)

		locales.extend(data["results"])

		if not data["next"]:
			break

		page += 1

	return locales


def get_ff_project(slug):
	try:
		r = session.get(f"{PONTOON_API_URL}projects/{slug}/", params={"fields": "name,localizations"}, timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		logging.critical("%s\n%r", e, r.text)
		sys.exit(1)
	except (RequestException, JSONDecodeError) as e:
		logging.critical("%s: %s", type(e).__name__, e)
		sys.exit(1)

	return data


def get_project(slug):
	try:
		r = session.get(
			f"{PONTOON_API_URL}projects/{slug}/",
			params={"fields": "name,localizations,missing_strings,total_strings,approved_strings,unreviewed_strings"},
			timeout=30,
		)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		logging.critical("%s\n%r", e, r.text)
		sys.exit(1)
	except (RequestException, JSONDecodeError) as e:
		logging.critical("%s: %s", type(e).__name__, e)
		sys.exit(1)

	return data


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	logging.basicConfig(level=logging.INFO, format="%(filename)s: [%(asctime)s]  %(levelname)s: %(message)s")

	now = datetime.now(timezone.utc)

	adir = os.path.join(f"{now:w%V-%G}", "localization")

	os.makedirs(adir, exist_ok=True)

	print("## 🔠 Pontoon Localization (pontoon.mozilla.org)\n")

	print(f"Data as of: {now:%Y-%m-%d %H:%M:%S%z}\n")

	locales = get_locales()
	languages = {alocale["code"].split("-", 1)[0] for alocale in locales}

	print(f"### Total languages / locales: {len(languages):n} / {len(locales):n}\n")

	ff_projects = {}
	ff_project_locales = {}

	for slug in FF_PROJECTS:
		data = get_ff_project(slug)

		print(f"* {data['name']} localizations: {len(data['localizations']):n}")

		ff_projects[slug] = data
		ff_project_locales[slug] = {alocale["locale"]["code"] for alocale in data["localizations"]}

	ff_locales = {alocale["locale"]["code"] for data in ff_projects.values() for alocale in data["localizations"]}

	print(f"\n**Total Firefox localizations**: {len(ff_locales):n}\n")

	for slug in PROJECTS:
		data = get_project(slug)
		alocales = {alocale["locale"]["code"] for alocale in data["localizations"]}

		print(f"### {data['name']} ({slug})\n\n{PONTOON_BASE_URL}projects/{slug}/\n")

		localizations_count = len(data["localizations"])
		complete = sorted(
			(alocale["locale"] for alocale in data["localizations"] if alocale["complete"]), key=operator.itemgetter("name")
		)
		complete_count = len(complete)

		print(f"#### Localizations: {localizations_count:n}\n")
		print(
			f"#### Localizations Complete: {complete_count:n} / {localizations_count:n} ({complete_count / localizations_count:.4%})\n"
		)
		print("\n".join(f"* {alocale['name']!r} ({alocale['code']})" for alocale in complete))

		labels = []
		localizations = {key: [] for key in ("Approved", "Unreviewed")}

		with open(os.path.join(adir, f"Pontoon_{slug}.csv"), "w", newline="", encoding="utf-8") as csvfile:
			writer = csv.writer(csvfile)

			writer.writerow(("name", "code", "approved", "unreviewed", "total"))

			for item in sorted(data["localizations"], key=operator.itemgetter("approved_strings"), reverse=True):
				writer.writerow((
					item["locale"]["name"],
					item["locale"]["code"],
					item["approved_strings"],
					item["unreviewed_strings"],
					item["total_strings"],
				))

				labels.append(item["locale"]["name"])

				localizations["Approved"].append(item["approved_strings"])
				localizations["Unreviewed"].append(item["unreviewed_strings"])

		output_stacked_bar_graph(
			adir,
			labels,
			localizations,
			f"Pontoon {data['name']} Localizations by Translated",
			"Localization",
			"Total Strings",
			"Strings",
		)

		print("\n#### Other Top Localizations by percentage Translated\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(alocale for alocale in data["localizations"] if not alocale["complete"]),
				key=operator.itemgetter("approved_strings"),
				reverse=True,
			),
			1,
		):
			rows.append((
				f"{item['approved_strings'] / item['total_strings']:.4%} ({item['approved_strings']:n} / {item['total_strings']:n})",
				f"{item['locale']['name']!r} ({item['locale']['code']})",
			))
			if i >= 10:
				break

		output_markdown_table(rows, ("Approved %", "Locale"))

		print(
			f"\n**Total Translated Strings**: {data['approved_strings']:n} / {data['total_strings']:n} ({data['approved_strings'] / data['total_strings']:.4%})\n"
		)

		print("#### Localizations with the most Unreviewed Strings\n")

		rows = []
		for i, item in enumerate(sorted(data["localizations"], key=operator.itemgetter("unreviewed_strings"), reverse=True), 1):
			rows.append((f"{item['unreviewed_strings']:n}", f"{item['locale']['name']!r} ({item['locale']['code']})"))
			if i >= 5:
				break

		output_markdown_table(rows, ("Unreviewed", "Locale"))

		print(
			f"\n**Total Unreviewed Strings**: {data['unreviewed_strings']:n} / {data['total_strings']:n} ({data['unreviewed_strings'] / data['total_strings']:.4%})\n"
		)

		print("#### Top Missing Locales by Population (number of native speakers)\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(
					alocale
					for alocale in locales
					# Japanese (ja) is supported, but does not use Pontoon
					if alocale["code"] in ff_locales and alocale["code"] not in alocales and alocale["code"] != "ja"
				),
				key=operator.itemgetter("population"),
				reverse=True,
			),
			1,
		):
			rows.append(
				[f"{i:n}", f"{item['population']:n}", f"{item['name']!r} ({item['code']})"]
				+ ["✔️" if item["code"] in ff_project_locales[slug] else "" for slug in FF_PROJECTS]
			)
			if i >= 10:
				break

		output_markdown_table(rows, ["#", "Population", "Locale"] + [ff_projects[slug]["name"] for slug in FF_PROJECTS])

		diff = ff_locales - alocales

		print(
			f"\n**Total Missing localizations**: {len(diff):n}\n\nMissing meaning it is supported by Firefox (see top of section above), but not yet by Thunderbird.\n"
		)


if __name__ == "__main__":
	main()
