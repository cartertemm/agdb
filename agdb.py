"""Audiogames.net database scraper"""


import sys
import time
import os
import random
import json
import re
import traceback
from urllib.parse import urlencode, urljoin
import requests
from bs4 import BeautifulSoup


def secure_filename(filename):
	"""Returns a secure version of the provided file.

	Function based off the one found in werkzeug.utils.
	"""
	_filename_ascii_strip_re = re.compile(r"[^A-Za-z0-9_.-]")
	_windows_device_files = (
		"CON",
		"AUX",
		"COM1",
		"COM2",
		"COM3",
		"COM4",
		"LPT1",
		"LPT2",
		"LPT3",
		"PRN",
		"NUL",
	)
	if isinstance(filename, str):
		from unicodedata import normalize
		filename = normalize("NFKD", filename).encode("ascii", "ignore")
		filename = filename.decode("ascii")
	for sep in (os.path.sep, os.path.altsep):
		if sep:
			filename = filename.replace(sep, " ")
	filename = str(_filename_ascii_strip_re.sub("", "_".join(filename.split()))).strip("._")
	if os.name == "nt" and filename and filename.split(".")[0].upper() in _windows_device_files:
		filename = "_" + filename
	return filename


class game:
	"""Represents a single game in the database"""
	def __init__(self, id, db_url):
		self.id = id
		self.db_url = db_url
		self.info = {}

	def parse(self):
		"""Requests the latest copy of the game, parsing all necessary info"""
		r = _requests_session().get(self.db_url)
		r.raise_for_status()
		# LXML must be used over html.parser
		# as there are a few instances of invalid HTML tags which appear to pollute the tree
		soup = BeautifulSoup(r.text, "lxml")
		for row in soup("tr"):
			row = row.findAll("td")
			key = row[0].text.rstrip(":")
			value = row[1]
			# if we're looking at a link
			if value.find("a"):
				value = value.find("a")["href"]
			else:
				value = value.text
			self.info[key] = value
		# traverse nodes until we locate heading level 2 "Community" or "Admin" tags
		# all descriptions are admin editable HTML, so better safe than sorry
		# also address a baffling condition in the Lonewolf entry where "Quick Links" is the first break to appear
		description = ""
		heading = soup.find("h2", text="Description")
		while True:
			heading = heading.findNext()
			if heading.name == "h2" and heading.text in ("Admin", "Community", "Quick Links"):
				break
			else:
				description += str(heading)
		self.info["description"] = description

	def diff(self, json_or_instance):
		"""Determines the differences (if any) from parsed game info and the provided object"""
		if not self.info:
			raise RuntimeError("Attempted to compare with unparsed 'game' object")
		if isinstance(json_or_instance, game):
			json_or_instance = json_or_instance.info
		d = {}
		new = self.to_dict()
		for k in new:
			if not k in json_or_instance or new[k] != json_or_instance[k]:
				d[k] = new[k]
		return d

	def save_html(self, path="db_games"):
		pass

	def to_dict(self):
		dct = {"id": self.id, "db_url": self.db_url}
		dct.update(self.info)
		return dct

	def __getattr__(self, attr):
		if attr in self.info:
			return self.info[attr]
		raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{attr}'")

	def __repr__(self):
		return f"game({self.id})"


class AgDB:
	base_url = "https://audiogames.net/"

	def __init__(self, json_file=None):
		self.games = []
		self.games_json = []
		self._html = None
		self.session = _requests_session()
		self.url = None
		if json_file and os.path.isfile(json_file):
			self.load_game_json(json_file)

	def load_game_json(self, filename_or_obj):
		if isinstance(filename_or_obj, str):
			filename_or_obj = open(filename_or_obj, "r")
		self.games_json = json.load(filename_or_obj)

	def save_game_json(self, filename):
		self.games_json = sorted(self.games_json, key=lambda k:k["id"])
		with open(filename, "w") as f:
			json.dump(self.games_json, f, indent=4)

	def get_games_from_url(self, url=None):
		"""Retrieves a list of all games in the database from a URL."""
		url = url or self.base_url
		self.url = url
		r = self.session.get(url)
		r.raise_for_status()
		self._html = r.text
		self.parse()

	def get_games_from_file(self, filename):
		"""Retrieves a list of all games in the database from disk.
		Used for testing without actually hitting the server with requests."""
		with open(filename, "r") as f:
			content = f.read()
		self._html = content
		self.parse()

	def parse(self, html=None):
		html = html or self._html
		# LXML must be used over html.parser
		# as there are a few instances of invalid HTML tags which appear to pollute the tree
		soup = BeautifulSoup(html, "lxml")
		form = soup.find("form", id="SelfSubmit")
		db_base = form["action"]
		options = form.findAll("option")
		for option in options:
			id = option["value"]
			if id == "Select":
				continue
			db_url = db_base + "&" + urlencode({"id": id})
			if not db_url.startswith("http"):
				db_url = urljoin(self.url, db_url)
			self.games.append(game(id, db_url))

	def update_if_needed(self, game):
		json_game = [i for i in self.games_json if i["id"] == game.id]
		if not json_game:
			print("adding "+game.id+" to database")
			self.games_json.append(game.to_dict())
			return True
		json_game = json_game[0]
		diff = game.diff(json_game)
		if diff:
			print("Updating "+game.id+" in database")
			idx = self.games_json.index(json_game)
			self.games_json[idx].update(diff)

	def get_game(self, game):
		for game in self.games:
			if game.lower() == game.id.lower() or game == game.db_url:
				return game

	def get_downloaded_games(self):
		return [i for i in self.games if self.info]


def _requests_session():
	session = requests.Session()
	session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:77.0) Gecko/20100101 Firefox/77.0"
	return session


if __name__ == "__main__":
	if len(sys.argv) < 2 or "-h" in sys.argv or "--help" in sys.argv:
		print("usage: "+__file__+" output.json")
		sys.exit()
	fn = sys.argv[-1]
	errors = 0
	ag = AgDB(fn)
	#ag.get_games_from_file("ag.html")
	ag.get_games_from_url()
	print(f"{len(ag.games)} games in database")
	for g in ag.games:
		try:
			print("retrieving "+g.id)
			g.parse()
			ag.update_if_needed(g)
			time.sleep(random.uniform(1, 3))
		except KeyboardInterrupt:
			break
		except:
			print("Exception occurred")
			traceback.print_exc()
			errors += 1
			print(f"error #{errors}")
			if errors > 5:
				print("error limit reached, postponing further download")
				break
			continue
	ag.save_game_json(fn)
