#!/bin/bash

# Copyright © Teal Dulcet

# Run: bash generate.sh

set -e

export LC_ALL=en_US.UTF-8

# 1 = Weekly, 2 = Monthly, 3 = Quarterly, 4 = Yearly
PERIOD=3

if [[ $# -ne 0 ]]; then
	echo "Usage: $0" >&2
	exit 1
fi

REPOSITORY='https://github.com/thunderbird/Thunderbird-Metrics'

date=${EPOCHSECONDS:-$(date +%s)}
printf -v date1 '%(w%V-%G)T' "$date"

if [[ $PERIOD -eq 1 ]]; then
	date="-1 week"
elif [[ $PERIOD -eq 2 ]]; then
	date="$(date +%Y-%m-15) -1 month"
elif [[ $PERIOD -eq 3 ]]; then
	date="$(date +%Y-%m-15) -3 months"
elif [[ $PERIOD -eq 4 ]]; then
	date="-1 year"
fi
date=$(date -d "$date" +%s)

if [[ $PERIOD -eq 1 ]]; then
	printf -v date2 'Week %(%V, %G)T' "$date"
elif [[ $PERIOD -eq 2 ]]; then
	printf -v date2 '%(%B %Y)T' "$date"
elif [[ $PERIOD -eq 3 ]]; then
	printf -v date2 'Quarter %s, %(%Y)T' $(( ($(printf '%(%m)T' "$date") - 1) / 3 + 1 )) "$date"
elif [[ $PERIOD -eq 4 ]]; then
	printf -v date2 '%(%Y)T' "$date"
fi

mkdir -p "$date1"/{bugzilla,github,mozilla_connect,addons,support,localization}

# {
# 	echo -e '---\n'
# 	for script in bugzilla.py github.py mozilla_connect.py pro_ideas.py stats.py crash_stats.py code_coverage.py addons.py sumo.py discourse.py pontoon.py weblate.py topicbox.py; do
# 		echo "$script" >&2
# 		python3 -X dev "$script"
# 		echo -e '\n---\n'
# 	done
# } >"$date1/email.md"
# exit

echo -e "Bugzilla/BMO, Phabricator, Crash Stats and Thunderbird Code Coverage\n"

cat <<EOF >"$date1/bugzilla/email.md"
Subject: Thunderbird Community Metrics $date2: Bugzilla, Phabricator, Crash Stats and Code Coverage

Hello Thunderbird Community,

Welcome to the Thunderbird Community Metrics, which are designed to complement Magnus’s existing “Thunderbird Metrics” e-mail, while providing data from additional sources. There are a total of six e-mails, covering 13 sources:

1. Bugzilla/BMO, Phabricator, Crash Stats and Thunderbird Code Coverage
2. GitHub
3. Thunderbird Stats, Mozilla Connect and Thunderbird Pro Ideas
4. Thunderbird Add-ons/ATN
5. Support (Mozilla Support/SUMO, Mozilla Discourse and Topicbox)
6. Localization (Pontoon and Weblate)

This is e-mail 1 of 6 of the Thunderbird Community Metrics. It includes inline graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

---

# 📊 Thunderbird Community Metrics $date2

$(time python3 -OO bugzilla.py)


$(time python3 -OO crash_stats.py)


$(time python3 -OO code_coverage.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-The Community Team
EOF

echo -e "\nGitHub\n"

cat <<EOF >"$date1/github/email.md"
Subject: Thunderbird Community Metrics $date2: GitHub

Hello Thunderbird Community,

This is e-mail 2 of 6 of the Thunderbird Community Metrics. It includes inline graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

---

# 📊 Thunderbird Community Metrics $date2

$(time python3 -OO github.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-The Community Team
EOF

echo -e "\nThunderbird Stats, Mozilla Connect and Thunderbird Pro Ideas\n"

cat <<EOF >"$date1/mozilla_connect/email.md"
Subject: Thunderbird Community Metrics $date2: Stats, Mozilla Connect and Pro Ideas

Hello Thunderbird Community,

This is e-mail 3 of 6 of the Thunderbird Community Metrics. It includes inline graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

---

# 📊 Thunderbird Community Metrics $date2

$(time python3 -OO stats.py)

$(time python3 -OO mozilla_connect.py)

$(time python3 -OO pro_ideas.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-The Community Team
EOF

echo -e "\nThunderbird Add-ons/ATN\n"

cat <<EOF >"$date1/addons/email.md"
Subject: Thunderbird Community Metrics $date2: Add-ons (extensions and themes)

Hello Thunderbird Community,

This is e-mail 4 of 6 of the Thunderbird Community Metrics. It includes inline graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

---

# 📊 Thunderbird Community Metrics $date2

$(time python3 -OO addons.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-The Community Team
EOF

echo -e "\nSupport (Mozilla Support Forum/SUMO, Mozilla Discourse and Topicbox)\n"

cat <<EOF >"$date1/support/email.md"
Subject: Thunderbird Community Metrics $date2: Support (Mozilla Support Forum, Mozilla Discourse and Topicbox)

Hello Thunderbird Community,

This is e-mail 5 of 6 of the Thunderbird Community Metrics. It includes inline graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

---

# 📊 Thunderbird Community Metrics $date2

$(time python3 -OO sumo.py)


$(time python3 -OO discourse.py)


$(time python3 -OO topicbox.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-The Community Team
EOF

echo -e "\nLocalization (Pontoon and Weblate)\n"

cat <<EOF >"$date1/localization/email.md"
Subject: Thunderbird Community Metrics $date2: Localization (Pontoon and Weblate)

Hello Thunderbird Community,

This is e-mail 6 of 6 of the Thunderbird Community Metrics. It includes inline graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

---

# 📊 Thunderbird Community Metrics $date2

$(time python3 -OO pontoon.py)


$(time python3 -OO weblate.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-The Community Team
EOF
