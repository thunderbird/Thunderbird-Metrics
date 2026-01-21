#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 crash_stats.py

import atexit
import base64
import csv
import io
import locale
import logging
import os
import platform
import re
import sys
from collections import Counter, namedtuple
from datetime import datetime, timedelta, timezone
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

CRASH_STATS_BASE_URL = "https://crash-stats.mozilla.org/"
CRASH_STATS_API_URL = f"{CRASH_STATS_BASE_URL}api/"

PRODUCTS = ("Thunderbird", "Firefox")
PRODUCT = "Thunderbird"

# 1 = Weekly, 2 = Monthly, 3 = Quarterly, 4 = Yearly
PERIOD = 3


def output_period(date):
	if PERIOD == 1:
		return f"Week {date:%V, %G}"
	if PERIOD == 2:
		return f"{date:%B %Y}"
	if PERIOD == 3:
		return f"Quarter {(date.month - 1) // 3 + 1}, {date:%Y}"
	if PERIOD == 4:
		return f"{date:%Y}"
	return None


# r"([]!#()*+.<>[\\_`{|}-])"
MARKDOWN_ESCAPE = re.compile(r"([]!#*<>[\\_`|])")


def output_markdown_table(rows, header, hide=False):
	rows.insert(0, header)
	rows = [[MARKDOWN_ESCAPE.sub(r"\\\1", col) for col in row] for row in rows]
	lens = [max(*map(len, col), 2) for col in zip(*rows)]
	rows.insert(1, ["-" * alen for alen in lens])
	aformat = " | ".join(f"{{:<{alen}}}" for alen in lens)

	if hide:
		print("<details>\n<summary>Click to show the table</summary>\n")

	print("\n".join(starmap(aformat.format, rows)))

	if hide:
		print("\n</details>")


def fig_to_data_uri(fig):
	with io.BytesIO() as buf:
		fig.savefig(buf, format="svg", bbox_inches="tight")
		plt.close(fig)

		# "data:image/svg+xml," + quote(buf.getvalue())
		return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def output_stacked_bar_graph(adir, labels, stacks, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(12, 8))

	ax.margins(0.01)

	widths = [timedelta(6)] + [(labels[i] - labels[i + 1]) * 0.9 for i in range(len(labels) - 1)]
	cum = [0] * len(labels)

	for name, values in stacks.items():
		ax.bar(labels, values, width=widths, bottom=cum, label=name)
		for i in range(len(cum)):
			cum[i] += values[i]

	ax.ticklabel_format(axis="y", useLocale=True)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def fromisoformat(date_string):
	return datetime.fromisoformat(date_string[:-1] + "+00:00" if date_string.endswith("Z") else date_string)


VERSION_PATTERN = re.compile(r"^([0-9]+)(?:\.([0-9]+)(?:\.([0-9]+)(?:\.([0-9]+))?)?)?(?:([ab])([0-9]+)?)?(?:(pre)([0-9])?)?")

Version = namedtuple("Version", ("major", "minor", "micro", "patch", "alpha_beta", "alpha_beta_ver", "pre", "pre_ver"))


def parse_version(version):
	version_res = VERSION_PATTERN.match(version)
	if not version_res:
		logging.error("Error parsing version %r", version)
		return None

	major, minor, micro, patch, alpha_beta, alpha_beta_ver, pre, pre_ver = version_res.groups()
	return Version(
		int(major),
		int(minor) if minor else 0,
		int(micro) if micro else 0,
		int(patch) if patch else 0,
		alpha_beta,
		int(alpha_beta_ver) if alpha_beta_ver else 0,
		pre,
		int(pre_ver) if pre_ver else 0,
	)


def output_verion(version):
	aversion = parse_version(version)
	if not aversion:
		return version

	release = None
	if aversion.alpha_beta:
		if aversion.alpha_beta == "a":
			release = "Daily"
		elif aversion.alpha_beta == "b":
			release = "Beta"
	elif version.endswith("esr"):
		release = "ESR"

	return f"{aversion.major}{f' {release}' if release else ''}"


def get_histogram(start_date, end_date):
	try:
		r = session.get(
			f"{CRASH_STATS_API_URL}SuperSearch/",
			params={
				# "product": PRODUCT,
				"date": (f">={start_date:%Y-%m-%d}", f"<{end_date:%Y-%m-%d}"),
				"_results_number": 0,
				"_histogram.date": "product",
				"_histogram_interval.date": "1w",
			},
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

	return data["facets"]["histogram_date"]


def get_aggregation(start_date, end_date):
	try:
		r = session.get(
			f"{CRASH_STATS_API_URL}SuperSearch/",
			params={
				"product": PRODUCT,
				"date": (f">={start_date:%Y-%m-%d}", f"<{end_date:%Y-%m-%d}"),
				"_results_number": 0,
				"_aggs.signature": "version",
			},
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

	return data["facets"]["signature"]


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	logging.basicConfig(level=logging.INFO, format="%(filename)s: [%(asctime)s]  %(levelname)s: %(message)s")

	now = datetime.now(timezone.utc)
	year = now.year
	month = now.month - 6
	if month < 1:
		year -= 1
		month += 12
	start_date = datetime(year, month, 1, tzinfo=timezone.utc)

	if PERIOD == 1:
		weekday = now.weekday()
		end_date = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(weekday, weeks=1)
	elif PERIOD == 2:
		year = now.year
		month = now.month - 1
		if month < 1:
			year -= 1
			month += 12
		end_date = datetime(year, month, 1, tzinfo=timezone.utc)
	elif PERIOD == 3:
		year = now.year
		month = now.month - (now.month - 1) % 3 - 3
		if month < 1:
			year -= 1
			month += 12
		end_date = datetime(year, month, 1, tzinfo=timezone.utc)
	elif PERIOD == 4:
		year = now.year - 1
		end_date = datetime(year, 1, 1, tzinfo=timezone.utc)

	adir = os.path.join(f"{now:w%V-%G}", "bugzilla")

	os.makedirs(adir, exist_ok=True)

	data = get_histogram(start_date, now)

	print("## 💥 Crash Stats (crash-stats.mozilla.org)\n")

	print(f"Data as of: {now:%Y-%m-%d %H:%M:%S%z}\n")

	labels = []
	stats = {product: [] for product in (PRODUCT,)}

	with open(os.path.join(adir, "Crash Stats.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.DictWriter(csvfile, ("Date", *PRODUCTS))

		writer.writeheader()

		rows = []
		for item in reversed(data):
			adate = fromisoformat(item["term"])
			astats = {product["term"]: product for product in item["facets"]["product"]}

			writer.writerow({"Date": f"{adate:%Y-%m-%d}", **{product: astats[product]["count"] for product in PRODUCTS}})

			rows.append((f"{adate:%Y-%m-%d}", f"{astats[PRODUCT]['count']:n}", f"{astats['Firefox']['count']:n}"))

			labels.append(adate)
			stats[PRODUCT].append(astats[PRODUCT]["count"])

	print("### Thunderbird Crashes by Week (past six months)\n")
	output_stacked_bar_graph(adir, labels, stats, "Thunderbird Crashes by Week", "Date", "Crashes", None)
	output_markdown_table(rows, ("Week", "Thunderbird Crashes", "Firefox Crashes"), True)

	print(f"\nPlease see {CRASH_STATS_BASE_URL}search/?product=Thunderbird for more information.")

	items = get_aggregation(end_date, now)

	print(f"\n### Top Thunderbird Crash Signatures ({output_period(end_date)})\n")

	rows = []
	for i, item in enumerate(items, 1):
		counts = Counter()
		for version in item["facets"]["version"]:
			counts.update({output_verion(version["term"]): version["count"]})

		rows.append((
			f"{i:n}",
			f"{item['count']:n}",
			item["term"],
			", ".join(f"{key}: {count:n}" for key, count in counts.most_common(5)),
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Crashes", "Signature", "Thunderbird Versions (top 5)"))


if __name__ == "__main__":
	main()
