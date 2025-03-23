# Solar Budget Application Development Plan

## 1. Project Setup
- [x] Initialize FastAPI project structure
- [x] Create requirements.txt with dependencies
- [x] Set up environment variables for API keys

## 2. Docker Setup
- [ ] Create Dockerfile
  - [ ] Use Python slim base image
  - [ ] Set up SQLite volume
- [ ] Create docker-compose.yml
- [ ] Write Synology NAS deployment steps

## 3. Data Collection
- [x] Implement Solcast API integration
  - [x] Get solar forecast data
  - [x] Handle rate limiting (max 10 calls/day)
  - [x] Cache data for 3 hours
- [x] Implement PSE API integration
  - [x] Get energy prices
  - [x] Cache daily price data
  - [x] Handle 16:00 next-day data updates

## 4. Data Processing
- [ ] Set up SQLite database for history
- [x] Convert 30min solar data to 15min intervals
- [x] Calculate energy amounts (kWh)
- [x] Calculate daily totals

## 5. Backend
- [x] Create FastAPI routes
- [x] Add data caching
- [x] Add error handling
- [ ] Schedule data updates

## 6. Frontend
- [x] Create simple web interface
- [x] Show bar charts for:
  - [x] Current day view
  - [x] Next day view
- [x] Add price overlay
- [x] Make it mobile-friendly

## 7. Testing & Documentation
- [ ] Test core functionality
- [ ] Write setup instructions
- [ ] Add user guide

## 8. Deployment
- [ ] Test on Synology NAS
- [ ] Set up backups
- [ ] Document recovery steps 