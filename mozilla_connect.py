#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 mozilla_connect.py

import atexit
import base64
import csv
import io
import json
import locale
import logging
import os
import platform
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
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

MOZILLA_CONNECT_BASE_URL = "https://connect.mozilla.org/"
MOZILLA_CONNECT_API_URL = f"{MOZILLA_CONNECT_BASE_URL}api/2.0/"

LABELS = ("Thunderbird", "Thunderbird Android", "Thunderbird for iOS")

STATUSES = ("new", "trending-idea", "needs_info", "investigating", "accepted", "not-right-now", "delivered", "declined")

LIMIT = 200


class HTMLToText(HTMLParser):
	__slots__ = ("output", "links", "images")

	def __init__(self):
		super().__init__()
		self.output = []
		self.links = []
		self.images = []

	def handle_starttag(self, tag, attrs):
		attrs = dict(attrs)
		if tag == "a":
			if "href" in attrs:
				self.links.append(attrs["href"])
		elif tag == "img":
			if "src" in attrs:
				self.images.append(attrs["src"])

	def handle_endtag(self, tag):
		if tag == "a":
			if self.links:
				self.output.append(f"<{self.links.pop()}>")
		elif tag == "img":
			if self.images:
				self.output.append(f"<{self.images.pop()}>")

	def handle_data(self, data):
		self.output.append(data)


def html_to_text(html):
	p = HTMLToText()
	p.feed(html)
	return " ".join("".join(p.output).split())


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

	widths = [timedelta(26)] + [(labels[i] - labels[i + 1]) * 0.9 for i in range(len(labels) - 1)]
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


def output_isoformat(date):
	output = date.isoformat()
	return output[:-6] + "Z" if output.endswith("+00:00") else output


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


def get_all_ideas(label):
	ideas = []
	cursor = None
	offset = 0

	while True:
		logging.info("\tOffset: %s", offset)

		try:
			r = session.get(
				f"{MOZILLA_CONNECT_API_URL}search",
				params={
					"q": f"SELECT id, author, subject, body, view_href, board, conversation, parent, kudos.sum(weight), post_time, status, depth FROM messages WHERE labels.text = {label!r} ORDER BY post_time ASC LIMIT {LIMIT}{f' CURSOR {cursor!r}' if cursor else ''}"
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

		ideas.extend(data["data"]["items"])

		if "next_cursor" not in data["data"]:
			break
		cursor = data["data"]["next_cursor"]

		offset += LIMIT

	return ideas


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	logging.basicConfig(level=logging.INFO, format="%(filename)s: [%(asctime)s]  %(levelname)s: %(message)s")

	end_date = datetime.now(timezone.utc)
	year = end_date.year
	month = end_date.month - 1
	if month < 1:
		year -= 1
		month += 12
	start_date = max(datetime(year - 10, 1, 1, tzinfo=timezone.utc), datetime(2022, 1, 1, tzinfo=timezone.utc))

	dates = []
	date = start_date
	while date < end_date:
		dates.append(date)

		year = date.year
		month = date.month + 1
		if month > 12:
			year += 1
			month -= 12
		date = date.replace(year=year, month=month)

	dates.pop()
	end_date = dates[-1]

	adir = os.path.join(f"{end_date:%Y-%m}", "mozilla_connect")

	os.makedirs(adir, exist_ok=True)

	file = os.path.join(f"{end_date:%Y-%m}", "Mozilla Connect.json")

	if not os.path.exists(file):
		ideas = {}

		start = time.perf_counter()

		for label in LABELS:
			logging.info("Label: %r", label)

			data = get_all_ideas(label)
			ideas[label] = data

		end = time.perf_counter()
		logging.info("Downloaded ideas in %s.", output_duration(timedelta(seconds=end - start)))

		with open(file, "w", encoding="utf-8") as f:
			json.dump(ideas, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			ideas = json.load(f)

	date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

	print("## 💡 Mozilla Connect (connect.mozilla.org)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	items = {idea["id"]: idea for item in ideas.values() for idea in item}
	labels = {}

	for label in LABELS:
		for idea in ideas[label]:
			labels.setdefault(idea["id"], []).append(label)

	aitems = [item for item in items.values() if not item["depth"]]
	duplicates = {item["id"]: [] for item in items.values()}

	for aid, item in items.items():
		if item["depth"]:
			if item["parent"]["id"] not in duplicates:
				logging.warning("Could not find idea: %s", item["parent"]["view_href"])
			duplicates.setdefault(item["parent"]["id"], []).append(aid)

	created = {(adate.year, adate.month): [] for adate in dates}
	deltas = []

	for item in items.values():
		adate = datetime.fromisoformat(item["post_time"]).astimezone(timezone.utc)
		created.setdefault((adate.year, adate.month), []).append(item)

		if "status" in item and not item["status"]["completed"]:
			deltas.append(date - adate)

	items_count = len(items)

	print(f"### Total Thunderbird Ideas/Discussions: {items_count:n}\n")

	board_counts = Counter(item["board"]["id"] for item in aitems)

	print("#### Boards\n")
	output_markdown_table([(key, f"{count:n}") for key, count in board_counts.most_common()], ("Board", "Count"))

	print("\n#### Labels\n")
	output_markdown_table([(label, f"{len(ideas[label]):n}") for label in LABELS], ("Label", "Count"))

	status_counts = Counter((item["status"]["key"], item["status"]["name"]) for item in aitems if "status" in item)
	idea_count = board_counts["ideas"]

	print("\n#### Idea Statuses\n")
	output_markdown_table(
		[
			(f"{name} ({key})", f"{count:n} / {idea_count:n} ({count / idea_count:.4%})")
			for (key, name), count in status_counts.most_common()
		],
		("Idea Status", "Count"),
	)

	completed_count = sum(1 for item in aitems if "status" in item and item["status"]["completed"])

	print(f"\nIdeas completed: {completed_count:n} / {idea_count:n} ({completed_count / idea_count:.4%})")

	mean = sum(deltas, timedelta()) / len(deltas)

	print(
		f"\n**Open Ideas Duration**\n* Average/Mean: {output_duration(mean)}\n* Median: {output_duration(statistics.median(deltas))}"
	)

	discussion_count = board_counts["discussions"]
	solved_count = sum(1 for item in aitems if item["board"]["id"] == "discussions" and item["conversation"]["solved"])

	print("\n#### Discussions\n")
	print(f"* Discussions solved: {solved_count:n} / {discussion_count:n} ({solved_count / discussion_count:.4%})")

	alabels = list(reversed(dates))
	created_status = {key: [] for key in STATUSES}
	created_label = {key: [] for key in LABELS}

	with open(os.path.join(adir, "Mozilla Connect_labels.csv"), "w", newline="", encoding="utf-8") as csvfile1, open(
		os.path.join(adir, "Mozilla Connect_statuses.csv"), "w", newline="", encoding="utf-8"
	) as csvfile2:
		writer1 = csv.DictWriter(csvfile1, ("Date", "Total Created", *LABELS))
		writer2 = csv.DictWriter(csvfile2, ("Date", "Total Created", *STATUSES))

		writer1.writeheader()
		writer2.writeheader()

		rows = []
		for date in reversed(dates):
			acreated = created[date.year, date.month]

			created_count = len(acreated)
			created_counts = Counter(item["board"]["id"] for item in acreated)
			label_counts = Counter(label for item in acreated for label in labels[item["id"]])
			status_counts = Counter((item["status"]["key"], item["status"]["name"]) for item in acreated if "status" in item)
			astatus_counts = {key: count for (key, _), count in status_counts.items()}

			writer1.writerow({"Date": f"{date:%B %Y}", "Total Created": created_count, **label_counts})
			writer2.writerow({"Date": f"{date:%B %Y}", "Total Created": created_count, **astatus_counts})

			rows.append((
				f"{date:%B %Y}",
				f"{created_count:n}",
				", ".join(f"{key}: {count:n}" for key, count in created_counts.most_common()),
				", ".join(f"{key}: {count:n}" for key, count in label_counts.most_common()),
				", ".join(f"{name}: {count:n}" for (_, name), count in status_counts.most_common()),
			))

			for key in STATUSES:
				created_status[key].append(astatus_counts.get(key, 0))
			for key in LABELS:
				created_label[key].append(label_counts[key])

	print("\n### Total Ideas/Discussions Created by Month\n")
	output_stacked_bar_graph(
		adir, alabels, created_status, "Mozilla Connect Ideas Created by Status and Month", "Date", "Total Created", "Idea Status"
	)
	print("(Note: Some ideas have two labels, so they are double counted in the below graph.)")
	output_stacked_bar_graph(
		adir,
		alabels,
		created_label,
		"Mozilla Connect Ideas/Discussions Created by Label and Month",
		"Date",
		"Total Created",
		"Label",
	)
	output_markdown_table(rows, ("Month", "Created", "Boards", "Labels", "Idea Statuses"), True)

	print("\n### Top Ideas/Discussions by Total Kudos\n")

	with open(os.path.join(adir, "Mozilla Connect_kudos.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.writer(csvfile)
		writer.writerow(("Kudos", "Total Kudos", "Date (UTC)", "Board", "Labels", "Idea Status", "Subject", "Body", "URL"))

		rows = []
		for i, item in enumerate(
			sorted(
				(item for item in aitems if "status" not in item or not item["status"]["completed"]),
				key=lambda x: x["kudos"]["sum"]["weight"],
				reverse=True,
			),
			1,
		):
			if not item["kudos"]["sum"]["weight"]:
				break
			kudos = sum(items[aid]["kudos"]["sum"]["weight"] for aid in duplicates[item["id"]])
			writer.writerow((
				f"{item['kudos']['sum']['weight']}{f' + {kudos}' if kudos else ''}",
				item["kudos"]["sum"]["weight"] + kudos,
				output_isoformat(datetime.fromisoformat(item["post_time"]).astimezone(timezone.utc)),
				item["board"]["id"],
				", ".join(labels[item["id"]]),
				item["status"]["name"] if "status" in item else "",
				item["subject"],
				html_to_text(item["body"]),
				item["view_href"],
			))
			if i <= 20:
				rows.append((
					f"{i:n}",
					f"{item['kudos']['sum']['weight']:n}{f' + {kudos:n}' if kudos else ''}",
					item["board"]["id"],
					", ".join(labels[item["id"]]),
					item["status"]["name"] if "status" in item else "-",
					item["subject"],
					item["view_href"],
				))

	output_markdown_table(rows, ("#", "Kudos", "Board", "Labels", "Idea Status", "Subject", "URL"))

	print(f"\nSee full ideas list: {MOZILLA_CONNECT_BASE_URL}t5/ideas/idb-p/ideas/label-name/thunderbird/tab/most-kudoed")

	print("\n### Top Ideas/Discussions by Total Duplicates\n")

	rows = []
	for i, item in enumerate(
		sorted(
			(item for item in aitems if "status" not in item or not item["status"]["completed"]),
			key=lambda x: len(duplicates[x["id"]]),
			reverse=True,
		),
		1,
	):
		dupes = sum(len(duplicates[aid]) for aid in duplicates[item["id"]])
		rows.append((
			f"{i:n}",
			f"{len(duplicates[item['id']]):n}{f' + {dupes:n}' if dupes else ''}",
			item["board"]["id"],
			", ".join(labels[item["id"]]),
			item["status"]["name"] if "status" in item else "-",
			item["subject"],
			item["view_href"],
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Duplicates", "Board", "Labels", "Idea Status", "Subject", "URL"))

	print("\n### Top Ideas/Discussions by Total Replies\n")

	rows = []
	for i, item in enumerate(
		sorted(
			(item for item in aitems if "status" not in item or not item["status"]["completed"]),
			key=lambda x: x["conversation"]["messages_count"],
			reverse=True,
		),
		1,
	):
		rows.append((
			f"{i:n}",
			f"{item['conversation']['messages_count']:n}",
			item["board"]["id"],
			", ".join(labels[item["id"]]),
			item["status"]["name"] if "status" in item else "-",
			item["subject"],
			item["view_href"],
		))
		if i >= 20:
			break

	output_markdown_table(rows, ("#", "Replies", "Board", "Labels", "Idea Status", "Subject", "URL"))


if __name__ == "__main__":
	main()
