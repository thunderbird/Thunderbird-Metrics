#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 pro_ideas.py

import atexit
import base64
import csv
import io
import json
import locale
import logging
import operator
import os
import platform
import re
import statistics
import sys
import time
from collections import Counter
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

PRO_IDEAS_BASE_URL = "https://ideas.tb.pro/"
PRO_IDEAS_API_URL = f"{PRO_IDEAS_BASE_URL}api/gateway/"

HEADERS = {"X-Organization": "ideas.tb.pro"}

LIMIT = 100

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


def fig_to_data_uri(fig):
	with io.BytesIO() as buf:
		fig.savefig(buf, format="svg", bbox_inches="tight")
		plt.close(fig)

		# "data:image/svg+xml," + quote(buf.getvalue())
		return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def output_stacked_bar_graph(adir, labels, stacks, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(10, 6))

	ax.margins(0.01)

	# Set the width for each bar in the bar graph to 90% of the time difference between them
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


def output_duration(delta):
	m, s = divmod(delta.seconds, 60)
	h, m = divmod(m, 60)
	y, d = divmod(delta.days, 365)
	ms, _us = divmod(delta.microseconds, 1000)
	text = []
	if y:
		text.append(f"{y:n} year{'s' if y != 1 else ''}")
	if y or d:
		text.append(f"{d:n} day{'s' if d != 1 else ''}")
	if y or d or h:
		text.append(f"{h:n} hour{'s' if h != 1 else ''}")
	if y or d or h or m:
		text.append(f"{m:n} minute{'s' if m != 1 else ''}")
	if y or d or h or m or s:
		text.append(f"{s:n} second{'s' if s != 1 else ''}")
	if not (y or d or h or m):
		text.append(f"{ms:n} millisecond{'s' if ms != 1 else ''}")

	return ", ".join(text)


def get_all_ideas():
	ideas = []
	states = []
	page = 1

	while True:
		logging.info("\tPage: %s", page)

		try:
			r = session.get(f"{PRO_IDEAS_API_URL}posts", headers=HEADERS, params={"page": page, "per_page": LIMIT}, timeout=30)
			r.raise_for_status()
			data = r.json()
		except HTTPError as e:
			logging.critical("%s\n%r", e, r.text)
			sys.exit(1)
		except (RequestException, JSONDecodeError) as e:
			logging.critical("%s: %s", type(e).__name__, e)
			sys.exit(1)

		ideas.extend(data["feature_requests"])
		states.extend(data["custom_states"])

		if len(data["feature_requests"]) < LIMIT:
			break

		page += 1

	return ideas, states


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

	start_date = max(
		datetime(year - (10 if PERIOD <= 2 else 20), 1, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)
	)
	if PERIOD == 1:
		weekday = start_date.weekday()
		if weekday:
			start_date -= timedelta(6 - weekday)
	elif PERIOD == 3:
		month = (start_date.month - 1) % 3
		if month:
			start_date = start_date.replace(month=start_date.month - month)
	elif PERIOD == 4:
		if start_date.month - 1:
			start_date = start_date.replace(month=1)

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
	# end_date = dates[-1]

	adir = os.path.join(f"{now:w%V-%G}", "mozilla_connect")

	os.makedirs(adir, exist_ok=True)

	file = os.path.join(f"{now:w%V-%G}", "Pro Ideas.json")

	if not os.path.exists(file):
		start = time.perf_counter()

		ideas, states = get_all_ideas()

		end = time.perf_counter()
		logging.info("Downloaded ideas in %s.", output_duration(timedelta(seconds=end - start)))

		with open(file, "w", encoding="utf-8") as f:
			json.dump({"requests": ideas, "states": states}, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			data = json.load(f)
			ideas = data["requests"]
			states = data["states"]

	astates = {state["id"]: state for state in states}

	date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

	print("## 💡 Thunderbird Pro Ideas (ideas.tb.pro)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	created = {get_period(adate): [] for adate in dates}
	deltas = []

	for item in ideas:
		adate = fromisoformat(item["created_at"])
		created.setdefault(get_period(adate), []).append(item)

		if item["status"] != "closed":
			deltas.append(date - adate)

	ideas_count = len(ideas)

	print(f"### Total Thunderbird Pro Ideas: {ideas_count:n}\n")

	state_counts = Counter(item["custom_state_id"] for item in ideas)

	print("#### States\n")
	output_markdown_table(
		[
			(astates[key]["name"], f"{count:n} / {ideas_count:n} ({count / ideas_count:.4%})")
			for key, count in state_counts.most_common()
		],
		("State", "Count"),
	)

	status_counts = Counter(item["status"] for item in ideas)

	print("\n#### Statuses\n")
	output_markdown_table(
		[(key, f"{count:n} / {ideas_count:n} ({count / ideas_count:.4%})") for key, count in status_counts.most_common()],
		("Status", "Count"),
	)

	completed_count = sum(1 for item in ideas if item["completed_at"])

	print(f"\nIdeas completed: {completed_count:n} / {ideas_count:n} ({completed_count / ideas_count:.4%})")

	mean = sum(deltas, timedelta()) / len(deltas)

	print(
		f"\n**Open Ideas Duration**\n* Average/Mean: {output_duration(mean)}\n* Median: {output_duration(statistics.median(deltas))}"
	)

	alabels = list(reversed(dates))
	created_status = {state["slug"]: [] for state in states}

	with open(os.path.join(adir, "Pro Ideas_states.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.DictWriter(csvfile, ("Date", "Total Created", *(state["slug"] for state in states)))

		writer.writeheader()

		rows = []
		for date in reversed(dates):
			acreated = created[get_period(date)]

			created_count = len(acreated)
			status_counts = Counter(item["custom_state_id"] for item in acreated)
			astatus_counts = {astates[key]["slug"]: count for key, count in status_counts.items()}

			writer.writerow({"Date": output_period(date), "Total Created": created_count, **astatus_counts})

			rows.append((
				output_period(date),
				f"{created_count:n}",
				", ".join(f"{astates[key]['name']}: {count:n}" for key, count in status_counts.most_common()),
			))

			for state in states:
				key = state["slug"]
				created_status[key].append(astatus_counts.get(key, 0))

	print(f"\n### Total Ideas Created by {PERIODS[PERIOD]}\n")
	output_stacked_bar_graph(
		adir, alabels, created_status, f"Thunderbird Pro Ideas Created by {PERIODS[PERIOD]}", "Date", "Total Created", "Status"
	)
	output_markdown_table(rows, (PERIODS[PERIOD], "Created", "Idea States"), True)

	print("\n### Top Ideas by Total Votes\n")

	with open(os.path.join(adir, "Pro Ideas_votes.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.writer(csvfile)
		writer.writerow(("Upvotes", "Total Votes", "Date", "State", "Status", "Title", "Description", "URL"))

		rows = []
		for i, item in enumerate(
			sorted(
				(item for item in ideas if not item["completed_at"] and item["status"] != "closed"),
				key=operator.itemgetter("upvotes_count", "votes_count_number"),
				reverse=True,
			),
			1,
		):
			if not item["votes_count_number"]:
				break
			writer.writerow((
				item["upvotes_count"],
				item["votes_count_number"],
				item["created_at"],
				astates[item["custom_state_id"]]["slug"],
				item["status"],
				item["title"],
				" ".join(item["description"].split()),
				f"{PRO_IDEAS_BASE_URL}p/{item['slug']}",
			))
			if i <= 10:
				rows.append((
					f"{i:n}",
					f"{item['upvotes_count']:n}",
					# f"{item['votes_count_number']:n}",
					astates[item["custom_state_id"]]["name"],
					item["status"],
					item["title"],
					f"{PRO_IDEAS_BASE_URL}p/{item['slug']}",
				))

	output_markdown_table(rows, ("#", "Upvotes", "State", "Status", "Title", "URL"))

	print(f"\nSee full ideas list: {PRO_IDEAS_BASE_URL}?sort=top")

	print("\n### Top Ideas by Total Comments\n")

	rows = []
	for i, item in enumerate(
		sorted(
			(item for item in ideas if not item["completed_at"] and item["status"] != "closed"),
			key=operator.itemgetter("public_comments_count"),
			reverse=True,
		),
		1,
	):
		rows.append((
			f"{i:n}",
			f"{item['public_comments_count']:n}",
			astates[item["custom_state_id"]]["name"],
			item["status"],
			item["title"],
			f"{PRO_IDEAS_BASE_URL}p/{item['slug']}",
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Comments", "State", "Status", "Title", "URL"))


if __name__ == "__main__":
	main()
