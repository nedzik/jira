#! /usr/bin/env python

import datetime
import os
import sys

from atlassian import Jira

DEFAULT_JQL = f"status = done and updated >= startOfDay(-28) and type in (bug, story)"


class FlowItem:
    def __init__(self, key, assignee, project, events) -> None:
        super().__init__()
        self.key = key
        self.assignee = assignee
        self.project = project
        self.events = sorted(events, key=lambda e: e.timestamp)

    @staticmethod
    def from_issue(issue, changes):
        return FlowItem(
            key=issue['key'], assignee=get_assignee_safely(issue), project=issue['fields']['project']['name'],
            events=[
                FlowEvent.from_history(h, i) for h in changes['histories'] for i in h['items'] if i['field'] == 'status'
            ]
        )

    def arrival(self):
        return next((e.timestamp for e in self.events if e.to_status.upper() == 'IN PROGRESS'), None)

    def departure(self):
        return next((e.timestamp for e in reversed(self.events) if e.to_status.upper() == 'DONE'), None)

    def get_cycle_time_breakdown(self):
        cycle_time_breakdown = {}
        start_timestamp_by_event_type = {}
        for event in self.events:
            start_timestamp_by_event_type[event.to_status] = event.timestamp
            if event.from_status in start_timestamp_by_event_type:
                timedelta = (event.timestamp - start_timestamp_by_event_type[event.from_status])
                cycle_time_breakdown[event.from_status] = \
                    cycle_time_breakdown.get(event.from_status, 0) + timedelta.days * 86400 + timedelta.seconds
        return cycle_time_breakdown

    def to_csv(self):
        arrival = self.arrival()
        departure = self.departure()
        journey = '->'.join([self.events[0].from_status] + [e.to_status for e in self.events])
        if arrival and departure:
            cycle_time = float((departure - arrival).days * 86440 + (departure - arrival).days)/86440
            cycle_time_breakdown = self.get_cycle_time_breakdown()
            in_progress_cycle_time = float(cycle_time_breakdown.get('In Progress', 0))/86400
            in_review_cycle_time = float(cycle_time_breakdown.get('In Review', 0))/86400
            ready_for_qa_cycle_time = float(cycle_time_breakdown.get('Ready for QA', 0))/86400
            in_qa_cycle_time = float(cycle_time_breakdown.get('IN QA', 0))/86400
            print(
                f"{self.key},{self.project},{self.assignee},{arrival:%Y-%m-%d},{departure:%Y-%m-%d},"
                f"{cycle_time:.1f},{in_progress_cycle_time:.1f},{in_review_cycle_time:.1f},"
                f"{ready_for_qa_cycle_time:.1f},{in_qa_cycle_time:.1f},{journey}"
            )
        else:
            print(f"{self.key},{self.project},{self.assignee},,,,,,,,{journey}")


class FlowEvent:
    def __init__(self, ) -> None:
        super().__init__()

    @staticmethod
    def from_history(event, event_item):
        flow_event = FlowEvent()
        flow_event.timestamp = datetime.datetime.strptime(event['created'], '%Y-%m-%dT%H:%M:%S.%f%z')
        flow_event.from_status = event_item['fromString']
        flow_event.to_status = event_item['toString']
        return flow_event


def get_assignee_safely(issue):
    return issue['fields']['assignee']['displayName'] if issue['fields']['assignee'] else None


if __name__ == '__main__':
    url = os.getenv('JIRA_URL', 'https://shiftkey.atlassian.net')
    username = os.getenv('JIRA_USERNAME')
    api_access_token = os.getenv('JIRA_API_TOKEN')
    if url and username and api_access_token:
        jira = Jira(url=url, username=username, password=api_access_token, cloud=True)
        jql = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JQL
        items = []
        start_at = 0
        while True:
            print(f"Using query '{jql}', from position {start_at} ...", file=sys.stderr)
            found = jira.jql(jql=jql, fields='assignee,project', limit=100, start=start_at)
            total = found.get('total', 0)
            print(f"Got {len(found['issues'])} out of {total} issues. Processing ...", file=sys.stderr)
            items += [i for i in [FlowItem.from_issue(i, jira.get_issue_changelog(i['key'])) for i in found['issues']]]
            if start_at + len(found['issues']) >= total: break
            start_at += len(found['issues'])
        print("Item,Project,Assignee,Arrival,Departure,CT,In Progress CT,In Review CT,Ready for QA CT,In QA CT,Journey")
        [i.to_csv() for i in items]
