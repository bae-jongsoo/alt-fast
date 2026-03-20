#!/bin/bash
# DB 마이그레이션 실행
alt db migrate

# 초기 데이터 시딩 (시스템 파라미터 기본값 등)
# alt db seed  (필요 시)
