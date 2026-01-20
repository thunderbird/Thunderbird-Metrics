#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 addons.py

import atexit
import base64
import csv
import http.client
import io
import json
import locale
import logging
import operator
import os
import platform
import re
import sys
import textwrap
import time
from collections import Counter, namedtuple
from datetime import datetime, timedelta, timezone
from itertools import starmap
from json.decoder import JSONDecodeError
from urllib.parse import urlparse, urlunparse

import matplotlib.pyplot as plt
import requests
import urllib3
from requests.exceptions import HTTPError, RequestException

locale.setlocale(locale.LC_ALL, "")

session = requests.Session()
session.headers["User-Agent"] = (
	f"Thunderbird Metrics ({session.headers['User-Agent']} {platform.python_implementation()}/{platform.python_version()})"
)
session.mount(
	"https://",
	requests.adapters.HTTPAdapter(max_retries=urllib3.util.Retry(5, status_forcelist=(http.client.BAD_GATEWAY,), backoff_factor=1)),
)
atexit.register(session.close)

ADDONS_SERVER_BASE_URL = "https://addons.thunderbird.net/"
# Version 5 API is not yet supported by ATN
ADDONS_SERVER_API_URL = f"{ADDONS_SERVER_BASE_URL}api/v4/"

APP = "thunderbird"

LANG = "en-US"

LIMIT = 50

VERBOSE = False

# 1 = Weekly, 2 = Monthly, 3 = Quarterly, 4 = Yearly
PERIOD = 3

PERIODS = {1: "Week", 2: "Month", 3: "Quarter", 4: "Year"}


def get_period(date):
	if PERIOD == 1:
		cal = date.isocalendar()
		return cal.year, cal.week
	if PERIOD == 2:
		return date.year, date.month
	if PERIOD == 3:
		return date.year, (date.month - 1) // 3
	if PERIOD == 4:
		return date.year
	return None


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


def output_emojis(addon):
	text = []

	if addon["is_disabled"]:
		text.append("⛔")
	if addon["is_experimental"]:
		text.append("⚠️")
	if addon["is_source_public"]:
		text.append("📜")
	if addon["contributions_url"]:
		text.append("❤️")
	if addon["requires_payment"]:
		text.append("💲")
	if addon["public_stats"]:
		text.append("📈")

	return "".join(text)


def fig_to_data_uri(fig):
	with io.BytesIO() as buf:
		fig.savefig(buf, format="svg", bbox_inches="tight")
		plt.close(fig)

		# "data:image/svg+xml," + quote(buf.getvalue())
		return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def output_stacked_bar_graph(adir, labels, stacks, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(12, 8))

	ax.margins(0.01)
	if sum(sum(v) > 100 for v in zip(*stacks.values())) == 1:
		ax.set_ylim(top=100)

	days = 6 if PERIOD == 1 else 26 if PERIOD == 2 else 81 if PERIOD == 3 else 328 if PERIOD == 4 else 0
	widths = [timedelta(days)] + [(labels[i] - labels[i + 1]) * 0.9 for i in range(len(labels) - 1)]
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


def remove_locale_url(astr):
	url = urlparse(astr)
	return urlunparse(url._replace(path=url.path[6:])) if url.path.startswith("/en-US") else astr


VERSION_PART_MAX = (1 << 16) - 1

VERSION_PATTERN = re.compile(
	r"^([0-9]+|\*)(?:\.([0-9]+|\*)(?:\.([0-9]+|\*)(?:\.([0-9]+|\*))?)?)?(?:([ab])([0-9]+)?)?(?:(pre)([0-9])?)?"
)

Version = namedtuple("Version", ("major", "minor", "micro", "patch", "alpha_beta", "alpha_beta_ver", "pre", "pre_ver"))


def parse_version(version):
	version_res = VERSION_PATTERN.match(version)
	if not version_res:
		logging.error("Error parsing version %r", version)
		return None

	major, minor, micro, patch, alpha_beta, alpha_beta_ver, pre, pre_ver = version_res.groups()
	return Version(
		VERSION_PART_MAX if major == "*" else int(major),
		(VERSION_PART_MAX if minor == "*" else int(minor)) if minor else 0,
		(VERSION_PART_MAX if micro == "*" else int(micro)) if micro else 0,
		(VERSION_PART_MAX if patch == "*" else int(patch)) if patch else 0,
		alpha_beta or "z",
		int(alpha_beta_ver) if alpha_beta_ver else 0,
		pre or "z",
		int(pre_ver) if pre_ver else 0,
	)


def is_compatible(version, addon_version):
	compat = addon_version["compatibility"][APP]

	return parse_version(compat["min"]) <= version and parse_version(compat["max"]) >= version


def get_tb_versions():
	try:
		r = session.get("https://product-details.mozilla.org/1.0/thunderbird_versions.json", timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		logging.critical("%s\n%r", e, r.text)
		sys.exit(1)
	except (RequestException, JSONDecodeError) as e:
		logging.critical("%s: %s", type(e).__name__, e)
		sys.exit(1)

	return data


def get_languages():
	try:
		r = session.get("https://product-details.mozilla.org/1.0/languages.json", timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		logging.error("%s\n%r", e, r.text)
		return {}
	except (RequestException, JSONDecodeError) as e:
		logging.error("%s: %s", type(e).__name__, e)
		return {}

	return data


def get_addons(atype):
	addons = []
	page = 1

	while True:
		logging.info("\tPage %s (%s)", page, len(addons))

		try:
			r = session.get(
				f"{ADDONS_SERVER_API_URL}addons/search/",
				params={"app": APP, "type": atype, "lang": LANG, "sort": "created", "page_size": LIMIT, "page": page},
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

		addons.extend(data["results"])

		if not data["next"]:
			break

		page += 1

	return addons


def get_addon_versions(addon_id):
	versions = []
	page = 1

	while True:
		logging.info("\tPage %s (%s)", page, len(versions))

		try:
			r = session.get(
				f"{ADDONS_SERVER_API_URL}addons/addon/{addon_id}/versions/",
				params={"lang": LANG, "page_size": LIMIT, "page": page},
				timeout=30,
			)
			r.raise_for_status()
			data = r.json()
		except HTTPError as e:
			logging.error("%s\n%r", e, r.text)
			if r.status_code in {http.client.UNAUTHORIZED, http.client.NOT_FOUND}:
				return versions
			sys.exit(1)
		except (RequestException, JSONDecodeError) as e:
			logging.critical("%s: %s", type(e).__name__, e)
			sys.exit(1)

		versions.extend(data["results"])

		if not data["next"]:
			break

		page += 1

	return versions


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	logging.basicConfig(level=logging.INFO, format="%(filename)s: [%(asctime)s]  %(levelname)s: %(message)s")

	now = datetime.now(timezone.utc)
	if PERIOD == 1:
		year = now.year
		month = now.month
		day = now.day - now.weekday() - 7
		if day < 1:
			month -= 1
			if month < 1:
				year -= 1
				# month += 12
	elif PERIOD == 2:
		year = now.year
		month = now.month - 1
		if month < 1:
			year -= 1
			# month += 12
	elif PERIOD == 3:
		year = now.year
		month = now.month - 3
		if month < 1:
			year -= 1
			# month += 12
	elif PERIOD == 4:
		year = now.year - 1

	start_date = datetime(year - (10 if PERIOD <= 2 else 20), 1, 1, tzinfo=timezone.utc)
	if PERIOD == 1:
		weekday = start_date.weekday()
		if weekday:
			start_date -= timedelta(6 - weekday)

	dates = []
	date = start_date
	while date < now:
		dates.append(date)

		if PERIOD == 1:
			date += timedelta(weeks=1)
		elif PERIOD == 2:
			year = date.year
			month = date.month + 1
			if month > 12:
				year += 1
				month -= 12
			date = date.replace(year=year, month=month)
		elif PERIOD == 3:
			year = date.year
			month = date.month + 3
			if month > 12:
				year += 1
				month -= 12
			date = date.replace(year=year, month=month)
		elif PERIOD == 4:
			year = date.year + 1
			date = date.replace(year=year)

	dates.pop()
	end_date = dates[-1]

	adir = os.path.join(f"{now:%G-%V}", "addons")

	os.makedirs(adir, exist_ok=True)

	print("## 🧩 Thunderbird Add-ons/ATN (addons.thunderbird.net)\n")

	tb_versions = get_tb_versions()

	aversions = [
		(parse_version(version), version, name)
		for version, name in [
			(tb_versions[key], name)
			for key, name in (
				("LATEST_THUNDERBIRD_NIGHTLY_VERSION", "Daily"),
				("LATEST_THUNDERBIRD_DEVEL_VERSION", "Beta"),
				("LATEST_THUNDERBIRD_VERSION", "Release"),
				("THUNDERBIRD_ESR_NEXT", "Next ESR"),
				("THUNDERBIRD_ESR", "ESR"),
			)
			if tb_versions[key]
		]
		+ [("115.18.0", "Old ESR")]
	]

	file = os.path.join(f"{now:%G-%V}", "languages.json")

	if not os.path.exists(file):
		languages = get_languages()

		with open(file, "w", encoding="utf-8") as f:
			json.dump(languages, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			languages = json.load(f)

	for atype, name in (("extension", "Extension"), ("statictheme", "Theme")):
		print(f"### {name}s\n")

		file = os.path.join(f"{now:%G-%V}", f"ATN_{atype}s.json")

		if not os.path.exists(file):
			start = time.perf_counter()

			addons = get_addons(atype)

			end = time.perf_counter()
			logging.info("Downloaded add-ons in %s seconds.", end - start)

			with open(file, "w", encoding="utf-8") as f:
				json.dump(addons, f, ensure_ascii=False, indent="\t")
		else:
			with open(file, encoding="utf-8") as f:
				addons = json.load(f)

		file = os.path.join(f"{now:%G-%V}", f"ATN_{atype}_versions.json")

		if not os.path.exists(file):
			addon_versions = {}

			start = time.perf_counter()

			for addon in addons:
				logging.info("%s: %s %r", atype, addon["id"], addon["slug"])
				addon_versions[f"{addon['id']}-{addon['slug']}"] = get_addon_versions(addon["id"])

			end = time.perf_counter()
			logging.info("Downloaded add-on versions in %s seconds.", end - start)

			with open(file, "w", encoding="utf-8") as f:
				json.dump(addon_versions, f, ensure_ascii=False, indent="\t")
		else:
			with open(file, encoding="utf-8") as f:
				addon_versions = json.load(f)

		items = [
			addon for addon in addons if any(is_compatible(aversion, addon["current_version"]) for aversion, _, _ in aversions)
		]

		date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

		print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

		addons_count = len(addons)
		duplicates_count = {key: addons_count - len({addon[key] for addon in addons}) for key in ("id", "slug", "guid")}

		print(f"#### Total {name}s: {addons_count:n}\n")

		if any(duplicates_count.values()):
			print(f"({', '.join(f'duplicate {key}s: {value:n}' for key, value in duplicates_count.items() if value)})\n")

		# disabled_count = sum(1 for addon in addons if addon["is_disabled"])
		experimental_count = sum(1 for addon in addons if addon["is_experimental"])
		source_public_count = sum(1 for addon in addons if addon["is_source_public"])
		contribution_count = sum(1 for addon in addons if addon["contributions_url"])
		requires_payment_count = sum(1 for addon in addons if addon["requires_payment"])
		public_stats_count = sum(1 for addon in addons if addon["public_stats"])

		output_markdown_table(
			[
				("⚠️ Marked Experimental", f"{experimental_count:n} / {addons_count:n} ({experimental_count / addons_count:.4%})"),
				("📜 Open Source", f"{source_public_count:n} / {addons_count:n} ({source_public_count / addons_count:.4%})"),
				("❤️ Requests donations", f"{contribution_count:n} / {addons_count:n} ({contribution_count / addons_count:.4%})"),
				(
					"💲 Requires payment",
					f"{requires_payment_count:n} / {addons_count:n} ({requires_payment_count / addons_count:.4%})",
				),
				("📈 Has public stats", f"{public_stats_count:n} / {addons_count:n} ({public_stats_count / addons_count:.4%})"),
			],
			("Type", "Count"),
		)

		print(f"\n##### {name}s compatible with recent Thunderbird versions\n")

		rows = []
		for aversion, version, aname in aversions:
			latest_count = sum(1 for addon in addons if is_compatible(aversion, addon["current_version"]))
			any_count = sum(
				1
				for addon in addons
				if any(
					is_compatible(aversion, addon_version)
					for addon_version in addon_versions[f"{addon['id']}-{addon['slug']}"] or (addon["current_version"],)
					if APP in addon_version["compatibility"]
				)
			)

			rows.append((
				f"Thunderbird {aname} ({version})",
				f"{latest_count:n} / {addons_count:n} ({latest_count / addons_count:.4%})",
				f"{any_count:n} / {addons_count:n} ({any_count / addons_count:.4%})",
			))

		output_markdown_table(rows, ("Thunderbird Version", "Latest Add-on Version Count", "Any Add-on Version Count"))

		print(f"\nTotal compatible: {len(items):n} / {addons_count:n} ({len(items) / addons_count:.4%})")

		category_counts = Counter(
			category for addon in addons if APP in addon["categories"] for category in addon["categories"][APP]
		)

		print(f"\n##### Top {name} Categories\n")

		output_markdown_table([(f"{count:n}", key) for key, count in category_counts.most_common(10)], ("Count", "Category"))

		if VERBOSE:
			tags_counts = Counter(tag for addon in addons for tag in addon["tags"] if tag != "firefox57")

			print(f"\n##### Top {name} Tags\n")

			output_markdown_table([(f"{count:n}", key) for key, count in tags_counts.most_common(10)], ("Count", "Tag"))

		locale_counts = Counter(addon["default_locale"] for addon in addons)

		print(f"\n##### Top {name} Default Locales\n")

		output_markdown_table(
			[
				(f"{count:n}", key, languages[key]["English"] if key in languages else "")
				for key, count in locale_counts.most_common(10)
			],
			("Count", "Locale", "Name"),
		)

		created = {}
		updated = {}
		updates = {}

		for addon in addons:
			date = fromisoformat(addon["created"])
			created.setdefault(get_period(date), []).append(addon)

			date = fromisoformat(addon["last_updated"])
			updated.setdefault(get_period(date), []).append(addon)

			for version in addon_versions[f"{addon['id']}-{addon['slug']}"] or (addon["current_version"],):
				date = fromisoformat(max(file["created"] for file in version["files"]))
				updates.setdefault(get_period(date), []).append(addon)

		labels = list(reversed(dates))
		created_status = {key: [] for key in ("Created",)}
		updates_status = {key: [] for key in ("Updates",)}

		with open(os.path.join(adir, f"ATN_{atype}s_created.csv"), "w", newline="", encoding="utf-8") as csvfile1, open(
			os.path.join(adir, f"ATN_{atype}_updates.csv"), "w", newline="", encoding="utf-8"
		) as csvfile2:
			writer1 = csv.DictWriter(csvfile1, ("Date", "Total Created", *category_counts))
			writer2 = csv.writer(csvfile2)

			writer1.writeheader()
			writer2.writerow(("Date", "Total Updates"))

			rows1 = []
			rows2 = []
			for date in reversed(dates):
				adate = get_period(date)

				acreated = created.get(adate, [])
				acategory_counts = Counter(
					category for addon in acreated if APP in addon["categories"] for category in addon["categories"][APP]
				)
				created_count = len(acreated)

				updates_count = len(updates.get(adate, []))

				writer1.writerow({"Date": output_period(date), "Total Created": created_count, **acategory_counts})
				writer2.writerow((output_period(date), updates_count))

				rows1.append((
					output_period(date),
					f"{created_count:n}",
					", ".join(f"{key}: {count:n}" for key, count in acategory_counts.most_common()),
				))
				rows2.append((output_period(date), f"{updates_count:n}"))

				created_status["Created"].append(created_count)
				updates_status["Updates"].append(updates_count)

		print(f"\n#### Total {name}s Created by {PERIODS[PERIOD]}\n")
		output_stacked_bar_graph(
			adir, labels, created_status, f"ATN {name}s Created by {PERIODS[PERIOD]}", "Date", "Total Created", None
		)
		output_markdown_table(rows1, (PERIODS[PERIOD], "Created", "Categories"), True)

		print(f"\n#### Total {name} Updates by {PERIODS[PERIOD]}\n")
		output_stacked_bar_graph(
			adir, labels, updates_status, f"ATN {name} Updates by {PERIODS[PERIOD]}", "Date", "Total Updates", None
		)
		output_markdown_table(rows2, (PERIODS[PERIOD], "Updates"), True)

		version = parse_version(tb_versions["LATEST_THUNDERBIRD_VERSION"])

		print(f"\n#### {name}s Created ({output_period(end_date)})\n")

		rows = []
		for i, item in enumerate(created.get(get_period(end_date), []), 1):
			rows.append((
				f"{i:n}",
				f"{fromisoformat(item['created']):%Y-%m-%d}",
				output_emojis(item),
				item["name"],
				textwrap.shorten(item["summary"], 50, placeholder="…") if item["summary"] else "-",
				", ".join(
					f"{author['name']!r} ({author['username']})" if author["name"] != author["username"] else author["username"]
					for author in item["authors"]
				),
				item["current_version"]["version"],
				remove_locale_url(item["url"]),
			))

		output_markdown_table(rows, ("#", "Created", "", "Name", "Summary", "Authors", "Version", "URL"))

		if atype == "extension":
			print("\nAlso see: https://thunderbird.github.io/webext-reports/recent-addition.html")

		print(f"\n#### {name}s Updated ({output_period(end_date)})\n")

		rows = []
		for i, item in enumerate(
			sorted(updated.get(get_period(end_date), []), key=operator.itemgetter("last_updated"), reverse=True), 1
		):
			rows.append((
				f"{i:n}",
				f"{fromisoformat(item['last_updated']):%Y-%m-%d}",
				output_emojis(item),
				item["name"],
				textwrap.shorten(item["summary"], 50, placeholder="…") if item["summary"] else "-",
				", ".join(
					f"{author['name']!r} ({author['username']})" if author["name"] != author["username"] else author["username"]
					for author in item["authors"]
				),
				item["current_version"]["version"],
				remove_locale_url(item["url"]),
			))

		output_markdown_table(rows, ("#", "Updated", "", "Name", "Summary", "Authors", "Version", "URL"))

		if atype == "extension":
			print("\nAlso see: https://thunderbird.github.io/webext-reports/recent-activity.html")

		print(f"\n#### Top {name}s by Daily Users\n")

		rows = []
		for i, item in enumerate(sorted(items, key=operator.itemgetter("average_daily_users"), reverse=True), 1):
			compat = item["current_version"]["compatibility"][APP]
			rows.append((
				f"{i:n}",
				f"{item['average_daily_users']:n}",
				output_emojis(item),
				item["name"],
				", ".join(
					f"{author['name']!r} ({author['username']})" if author["name"] != author["username"] else author["username"]
					for author in item["authors"]
				),
				f"{'✔️' if is_compatible(version, item['current_version']) else '❌'} {compat['min']} - {compat['max']}",
				remove_locale_url(item["url"]),
			))
			if i >= 20:
				break

		output_markdown_table(rows, ("#", "Daily Users", "", "Name", "Authors", "Compatibility", "URL"))

		if atype == "extension":
			print("\nSee full list: https://thunderbird.github.io/webext-reports/all.html")

		# https://github.com/thunderbird/addons-server/issues/80
		if VERBOSE:
			print(f"\n#### Top {name}s by Weekly Downloads\n")

			rows = []
			for i, item in enumerate(sorted(items, key=operator.itemgetter("weekly_downloads"), reverse=True), 1):
				compat = item["current_version"]["compatibility"][APP]
				rows.append((
					f"{i:n}",
					f"{item['weekly_downloads']:n}",
					output_emojis(item),
					item["name"],
					", ".join(
						f"{author['name']!r} ({author['username']})" if author["name"] != author["username"] else author["username"]
						for author in item["authors"]
					),
					f"{'✔️' if is_compatible(version, item['current_version']) else '❌'} {compat['min']} - {compat['max']}",
					remove_locale_url(item["url"]),
				))
				if i >= 20:
					break

			output_markdown_table(rows, ("#", "Weekly Downloads", "", "Name", "Authors", "Compatibility", "URL"))

		print(f"\n#### Top {name}s by Total Reviews\n")

		rows = []
		for i, item in enumerate(sorted(items, key=lambda x: x["ratings"]["count"], reverse=True), 1):
			compat = item["current_version"]["compatibility"][APP]
			rows.append((
				f"{i:n}",
				f"{item['ratings']['count']:n}",
				f"{item['ratings']['bayesian_average']:n}",
				output_emojis(item),
				item["name"],
				", ".join(
					f"{author['name']!r} ({author['username']})" if author["name"] != author["username"] else author["username"]
					for author in item["authors"]
				),
				f"{'✔️' if is_compatible(version, item['current_version']) else '❌'} {compat['min']} - {compat['max']}",
				remove_locale_url(item["url"]),
			))
			if i >= 10:
				break

		output_markdown_table(rows, ("#", "Reviews", "Rating", "", "Name", "Authors", "Compatibility", "URL"))

		print(f"\n#### Top {name}s by Rating (Bayesian average, greater than 10 reviews)\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(addon for addon in items if addon["ratings"]["count"] >= 10),
				key=lambda x: x["ratings"]["bayesian_average"],
				reverse=True,
			),
			1,
		):
			compat = item["current_version"]["compatibility"][APP]
			rows.append((
				f"{i:n}",
				f"{item['ratings']['bayesian_average']:n}",
				f"{item['ratings']['count']:n}",
				output_emojis(item),
				item["name"],
				", ".join(
					f"{author['name']!r} ({author['username']})" if author["name"] != author["username"] else author["username"]
					for author in item["authors"]
				),
				f"{'✔️' if is_compatible(version, item['current_version']) else '❌'} {compat['min']} - {compat['max']}",
				remove_locale_url(item["url"]),
			))
			if i >= 10:
				break

		output_markdown_table(rows, ("#", "Rating", "Reviews", "", "Name", "Authors", "Compatibility", "URL"))

		print(f"\n#### Featured {name}s\n")

		rows = []
		for i, item in enumerate((addon for addon in addons if addon["is_featured"]), 1):
			compat = item["current_version"]["compatibility"][APP]
			rows.append((
				f"{i:n}",
				output_emojis(item),
				item["name"],
				textwrap.shorten(item["summary"], 50, placeholder="…") if item["summary"] else "-",
				", ".join(
					f"{author['name']!r} ({author['username']})" if author["name"] != author["username"] else author["username"]
					for author in item["authors"]
				),
				item["current_version"]["version"],
				f"{'✔️' if is_compatible(version, item['current_version']) else '❌'} {compat['min']} - {compat['max']}",
				remove_locale_url(item["url"]),
			))

		output_markdown_table(rows, ("#", "", "Name", "Summary", "Authors", "Version", "Compatibility", "URL"))

		print(f"\nAlso see: {ADDONS_SERVER_BASE_URL}{APP}/{'static-theme' if atype == 'statictheme' else atype}s/\n")


if __name__ == "__main__":
	main()
