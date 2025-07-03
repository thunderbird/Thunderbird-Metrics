#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 weblate.py

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

WEBLATE_API_URL = "https://hosted.weblate.org/api/"

WEBLATE_TOKEN = None

HEADERS = {"Authorization": f"Token {WEBLATE_TOKEN}"} if WEBLATE_TOKEN is not None else None

PROJECTS = ("tb-android",)

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


def get_languages():
	try:
		r = session.get(f"{WEBLATE_API_URL}languages/", headers=HEADERS, params={"page_size": LIMIT}, timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data["results"]


def get_project_stats(project):
	try:
		r = session.get(f"{WEBLATE_API_URL}projects/{project}/statistics/", headers=HEADERS, timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data


def get_project_langs(project):
	try:
		r = session.get(f"{WEBLATE_API_URL}projects/{project}/languages/", headers=HEADERS, timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data


def get_project_credits(project, start, end):
	try:
		r = session.get(
			f"{WEBLATE_API_URL}projects/{project}/credits/",
			headers=HEADERS,
			params={"start": start.isoformat(), "end": end.isoformat()},
			timeout=30,
		)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	logging.basicConfig(level=logging.INFO, format="%(filename)s: [%(asctime)s]  %(levelname)s: %(message)s")

	date = datetime.now(timezone.utc)
	year = date.year
	month = date.month - 1
	if month < 1:
		year -= 1
		month += 12
	start_date = datetime(year, month, 1, tzinfo=timezone.utc)
	end_date = datetime(date.year, date.month, 1, tzinfo=timezone.utc)

	adir = os.path.join(f"{start_date:%Y-%m}", "localization")

	os.makedirs(adir, exist_ok=True)

	print("## 🌐 Weblate Localization\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	languages = get_languages()
	langs = {alocale["code"].split("@", 1)[0].split("_", 1)[0] for alocale in languages}

	print(f"### Total languages / language codes: {len(langs):n} / {len(languages):n}\n")

	for slug in PROJECTS:
		stats = get_project_stats(slug)

		print(f"### {stats['name']} ({slug})\n\n{stats['url']}\n")

		data = get_project_langs(slug)
		langs = {lang["code"] for lang in data}

		langs_count = len(data)
		complete = sorted((lang["name"], lang["code"]) for lang in data if (lang["total"] - lang["readonly"]) == lang["approved"])
		complete_count = len(complete)

		print(f"#### Language codes: {langs_count:n}\n")
		print(f"#### Languages Complete: {complete_count:n} / {langs_count:n} ({complete_count / langs_count:.4%})\n")
		print("\n".join(f"* {name!r} ({code})" for (name, code) in complete))

		labels = []
		translations = {key: [] for key in ("Approved", "Unapproved")}

		with open(os.path.join(adir, f"Weblate_{slug}.csv"), "w", newline="", encoding="utf-8") as csvfile:
			writer = csv.writer(csvfile)

			writer.writerow(("name", "code", "approved", "translated", "total"))

			for item in sorted(data, key=lambda x: (x["approved"] + x["readonly"], x["translated"]), reverse=True):
				writer.writerow((
					item["name"],
					item["code"],
					item["approved"] + item["readonly"],
					item["translated"],
					item["total"],
				))

				labels.append(item["name"])

				translations["Approved"].append(item["approved"] + item["readonly"])
				# translations["Read only"].append(item["readonly"])
				translations["Unapproved"].append(item["translated"] - item["readonly"] - item["approved"])

		output_stacked_bar_graph(
			adir, labels, translations, f"Weblate {stats['name']} Languages by Approved", "Language", "Total Strings", "Strings"
		)

		print("\n#### Top Languages by percentage Approved\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(lang for lang in data if (lang["total"] - lang["readonly"]) != lang["approved"]),
				key=operator.itemgetter("approved"),
				reverse=True,
			),
			1,
		):
			rows.append((
				f"{item['approved'] / item['total']:.4%} ({item['approved']:n} / {item['total']:n})",
				f"{item['name']!r} ({item['code']})",
			))
			if i >= 5:
				break

		output_markdown_table(rows, ("Approved %", "Language"))

		print(
			f"\n**Total Approved Strings**: {stats['approved']:n} / {stats['total']:n} ({stats['approved'] / stats['total']:.4%})\n"
		)

		print("#### Languages with the most Unapproved Strings\n")

		rows = []
		for i, item in enumerate(sorted(data, key=lambda x: x["translated"] - x["readonly"] - x["approved"], reverse=True), 1):
			rows.append((f"{item['translated'] - item['readonly'] - item['approved']:n}", f"{item['name']!r} ({item['code']})"))
			if i >= 10:
				break

		output_markdown_table(rows, ("Unapproved", "Language"))

		print(
			f"\n**Total Unapproved Strings**: {stats['translated'] - stats['readonly'] - stats['approved']:n} / {stats['total']:n} ({(stats['translated'] - stats['readonly'] - stats['approved']) / stats['total']:.4%})\n"
		)

		print("#### Top Languages by percentage Translated (awaiting approval)\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(lang for lang in data if (lang["total"] - lang["readonly"]) != lang["approved"]),
				key=lambda x: x["translated"] / x["total"],
				reverse=True,
			),
			1,
		):
			rows.append((
				f"{item['translated'] / item['total']:.4%} ({item['translated']:n} / {item['total']:n})",
				f"{item['approved'] / (item['total'] - item['readonly']):.4%}",
				f"{item['name']!r} ({item['code']})",
			))
			if i >= 15:
				break

		output_markdown_table(rows, ("Translated %", "Approved %", "Language"))

		print(
			f"\n**Total Translated Strings**: {stats['translated']:n} / {stats['total']:n} ({stats['translated'] / stats['total']:.4%})\n"
		)

		print("#### Top Missing Languages by Population (number of native speakers)\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(lang for lang in languages if lang["code"] not in langs and "@" not in lang["code"]),
				key=operator.itemgetter("population"),
				reverse=True,
			),
			1,
		):
			rows.append((f"{i:n}", f"{item['population']:n}", f"{item['name']!r} ({item['code']})"))
			if i >= 10:
				break

		output_markdown_table(rows, ("#", "Population", "Language"))

		print(f"\n#### Top Contributors ({start_date:%B %Y})\n")

		if WEBLATE_TOKEN is not None:
			acredits = get_project_credits(slug, start_date, end_date)

			rows = []
			for i, item in enumerate(sorted(acredits, key=operator.itemgetter("change_count"), reverse=True), 1):
				rows.append((f"{item['change_count']:n}", item["full_name"]))
				if i >= 10:
					break

			output_markdown_table(rows, ("Changes", "User"))

			if len(acredits) <= 1:
				# print(f"\n**Error**: Need a token for the {slug!r} project with the 'reports.view' permission to get the credits for this table.")
				print("\n**Note**: Waiting on a token from MZLA to get the credits for this table.")
		else:
			print("**Note**: Waiting on a token from MZLA to get the credits for this table.")


if __name__ == "__main__":
	main()
