#!/usr/bin/env python

from contextlib import contextmanager
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from imaplib import IMAP4

from flask import Flask, Response, request, stream_with_context, session, redirect, url_for, render_template
import pytz


app = Flask(__name__)
app.secret_key = "YOUR SECRET KEY HERE"

@contextmanager
def imap_connection():
  host = session.get("host")
  if not host:
    host = request.form.get("host", "localhost")
    session["host"] = host
  user = session.get("user")
  if not user:
    user = request.form["user"]
    session["user"] = user
  password = session.get("password")
  if not password:
    password = request.form["password"]
    session["password"] = password
  with IMAP4(host) as connection:
    connection.starttls()
    connection.login(user, password)
    connection.enable("UTF8=ACCEPT")
    yield connection

@app.route("/", methods=("GET", "POST"))
def home():
  if ("user" in session or "user" in request.form) and ("password" in session or "password" in request.form):
    with imap_connection() as connection:
      messages = []
      count = connection.select()
      typ, data = connection.search(None, "ALL")
      for num in data[0].split():
        typ, data = connection.fetch(num, "(UID BODY.PEEK[HEADER])")
        uid = data[0][0].decode("utf-8").split(" ")[2]
        headers = data[0][1].decode("utf-8")
        from_ = None
        subject_ = None
        date_ = None
        for header in headers.split("\r\n"):
          if not header or header.startswith(" ") or header.startswith("\t"):
            continue
          try:
            key, value = map(str.strip, header.split(":", 1))
          except ValueError:
            pass
          else:
            key = key.lower()
            if key in ("subject", "from", "date"):
              decoded_value = ""
              for bit, charset in decode_header(value):
                if charset is not None:
                  bit = bit.decode(charset)
                if isinstance(bit, bytes):
                  bit = bit.decode("ascii")
                if bit:
                  decoded_value += bit
              decoded_value = decoded_value.strip()
              if key == "subject":
                subject_ = decoded_value
              elif key == "from":
                from_ = decoded_value
              elif key == "date":
                date_ = parsedate_to_datetime(decoded_value)
                if date_.tzinfo is not None:
                  date_ = date_.astimezone(pytz.utc)
                else:
                  date_ = pytz.utc.localize(date_)
            if subject_ is not None and from_ is not None and date_ is not None:
              break
        messages.append({"date": date_, "from": from_[:20], "uid": str(uid), "subject": subject_ or "(no subject)"})
    return render_template("message_list.html", messages=messages)
  else:
    return render_template("login.html")

@app.route("/message/<uid>")
def message(uid):
  with imap_connection() as connection:
    count = connection.select()
    typ, data = connection.uid("fetch", uid, "(RFC822)")
  message = message_from_bytes(data[0][1])
  from_ = message.get("From", "").strip()
  subject = message.get("Subject", "").strip()
  date = message.get("Date", "").strip()
  payload = None
  other_parts = []
  idx = 0
  for part in message.walk():
    typ = part.get_content_type()
    if typ == "text/plain":
      payload = part.get_payload(decode=True)
      if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    elif not typ.startswith("multipart/"):
      other_parts.append({"idx": str(idx), "content_type": part.get_content_type()})
    idx += 1
  return render_template("single_message.html", message={"from": from_,
                                                         "subject": subject,
                                                         "date": date,
                                                         "payload": payload,
                                                         "uid": uid}, other_parts=other_parts)

@app.route("/message/<uid>/part/<idx>")
def part(uid, idx):
  with imap_connection() as connection:
    count = connection.select()
    typ, data = connection.uid("fetch", uid, "(RFC822)")
  message = message_from_bytes(data[0][1])
  i = 0
  idx = int(idx)
  for part in message.walk():
    if i == idx:
      return Response(part.get_payload(decode=True), mimetype=part.get_content_type())
    i += 1
  return Response("part not found", mimetype="text/plain")

@app.route("/logout")
def logout():
  session.clear()
  return redirect(url_for("home"))

if __name__ == "__main__":
  app.run()
