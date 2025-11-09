import requests, json
from bs4 import BeautifulSoup

def search_events_tomorrow():

    def get_description(url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
        }

        response = requests.get(url, headers=headers)

        soup = BeautifulSoup(response.text, "html.parser")

        for script in soup.find_all("script", type="application/ld+json"):
            event_data = json.loads(script.string)
            if "description" in event_data:
                return event_data["description"]

        return ""

    def func(url: str, event_ids: set, event_info: dict):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
        }

        response = requests.get(url, headers=headers)

        soup = BeautifulSoup(response.text, "html.parser")

        for sec in soup.find_all("section", class_="event-card-details"):
            a = sec.find("a", class_="event-card-link")
            if not a:
                continue
            href = a.get("href")

            # Find last occurrence of ? and remove everything after it
            question_mark_pos = href.rfind('?')
            if question_mark_pos != -1:
                href = href[:question_mark_pos]

            if href.startswith("https://www.eventbrite.nl/e/") or href.startswith("https://www.eventbrite.com/e/"):
                # id
                mark_pos = href.rfind('-')
                id = href[mark_pos+1:]
                # title
                title_elem = sec.find("h3")
                title = title_elem.get_text(strip=True) if title_elem else "" # sec.get("aria-label")
                # date
                time = ""
                date_elem = sec.find_all("p", class_="Typography_root__487rx")
                for elem in date_elem:
                    elem_parts = elem.get_text(strip=True).split()
                    if elem_parts[-1] == "AM" or elem_parts[-1] == "PM":
                        time = elem_parts[-2] + " " + elem_parts[-1]
                        '''
                        if elem.startswith("Today"):
                            now = datetime.now()
                            elem_parts = elem.split()
                            date = now.strftime("%a, %b %-d,") + " " + elem_parts[-2] + " " + elem_parts[-1]
                        elif elem.startswith("Tomorrow"):
                            tomorrow = datetime.now() + timedelta(days=1)
                            elem_parts = elem.split()
                            date = tomorrow.strftime("%a, %b %-d,") + " " + elem_parts[-2] + " " + elem_parts[-1]
                        else:
                            date = elem
                        '''
                if time == "":
                    continue
                event_ids.add(id)
                description = get_description(href)
                event_info[id] = {"url": href, "title": title, "description": description, "time": time}

    event_ids = set()
    event_info = dict()

    url = f"https://www.eventbrite.com/d/netherlands--amsterdam/free--events--tomorrow/?lang=en"
    func(url, event_ids, event_info)

    assert len(event_info) == len(event_ids)
    return event_ids, event_info

event_ids, event_info = search_events_tomorrow()

print(f"Found {len(event_info)} events.")

with open('data.txt', 'w', encoding='utf-8') as f:
    for id in event_ids:
        f.write(str(event_info[id]))
        f.write("\n")
