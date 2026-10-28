"""Responses must describe committed state even when PostgreSQL commit is slow."""
import asyncio

import httpx
from helpers import login, seed_user
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.util.concurrency import await_only

from openkb_s4.models import User


async def test_created_account_is_committed_before_http_response_starts(api):
    app, client = api
    await seed_user(app, 'commit-admin', ['admin'])
    headers = await login(client, 'commit-admin')
    observed = []

    def slow_commit(_session):
        # A real transaction with deliberately slow commit exposes ordering;
        # retrying the following login would conceal this regression.
        await_only(asyncio.sleep(.75))

    async def inspect_response(scope, receive, send):
        async def checked_send(message):
            if message['type'] == 'http.response.start' and message['status'] == 201:
                async with app.state.sessions() as independent:
                    row = await independent.scalar(select(User.id).where(User.username == 'committed-before-response'))
                    observed.append(row is not None)
            await send(message)
        await app(scope, receive, checked_send)

    event.listen(Session, 'before_commit', slow_commit)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=inspect_response), base_url='http://testserver', cookies=client.cookies) as checked:
            response = await checked.post('/api/s4/v1/users', headers=headers, json={
                'username': 'committed-before-response', 'display_name': 'Commit consistency test',
                'person_id': 'commit-consistency-person', 'password': 'test-password-strong', 'roles': ['annotator']})
        assert response.status_code == 201, response.text
        assert observed == [True], 'HTTP 201 was emitted before the account transaction committed'
    finally:
        event.remove(Session, 'before_commit', slow_commit)
