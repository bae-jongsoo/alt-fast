SCTL = /Users/jongsoobae/Library/Python/3.9/bin/supervisorctl
CONF = /Users/jongsoobae/workspace/alt-fast/supervisord.conf

# 서버 상태
status:
	$(SCTL) -c $(CONF) status

# 전체 재시작
restart:
	$(SCTL) -c $(CONF) restart all

# 웹서버만 재시작
restart-api:
	$(SCTL) -c $(CONF) restart api

# 수집기만 재시작
restart-collectors:
	$(SCTL) -c $(CONF) restart collectors:*

# supervisord 시작 (서버 재부팅 후)
start:
	/Users/jongsoobae/Library/Python/3.9/bin/supervisord -c $(CONF)

# supervisord 종료
stop:
	$(SCTL) -c $(CONF) shutdown

# 이벤트 트레이더만 재시작
restart-event-trader:
	$(SCTL) -c $(CONF) restart traders:trader-event

# 로그 (이벤트 트레이더)
log-event-trader:
	tail -f /var/log/alt-fast/trader-event.log /var/log/alt-fast/trader-event.err.log

# 로그 (API)
log-api:
	tail -f /var/log/alt-fast/api.err.log

# 로그 (배포)
log-deploy:
	tail -f /var/log/alt-fast/deploy.log

# 로그 (수집기 전체)
log-collectors:
	tail -f /var/log/alt-fast/news.log /var/log/alt-fast/market.log /var/log/alt-fast/dart.log /var/log/alt-fast/trader.log

# 수동 배포
deploy:
	./scripts/deploy.sh

# 프론트 빌드
build-front:
	cd frontend && npm run build

# nginx 리로드
nginx-reload:
	nginx -s reload

# DB 접속
db:
	docker exec -it my-postgres psql -U postgres -d alt_fast

# 셸
shell:
	cd backend && .venv/bin/ipython -i shell.py

.PHONY: status restart restart-api restart-collectors restart-event-trader start stop log-api log-event-trader log-deploy log-collectors deploy build-front nginx-reload db shell
