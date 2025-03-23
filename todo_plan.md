# Solar Budget Application Development Plan

## 1. Project Setup
- [ ] Initialize FastAPI project structure
- [ ] Create requirements.txt with dependencies
- [ ] Set up environment variables for API keys

## 2. Docker Setup
- [ ] Create Dockerfile
  - [ ] Use Python slim base image
  - [ ] Set up SQLite volume
- [ ] Create docker-compose.yml
- [ ] Write Synology NAS deployment steps

## 3. Data Collection
- [ ] Implement Solcast API integration
  - [ ] Get solar forecast data
  - [ ] Handle rate limiting (max 10 calls/day)
  - [ ] Cache data for 3 hours
- [ ] Implement PSE API integration
  - [ ] Get energy prices
  - [ ] Cache daily price data
  - [ ] Handle 16:00 next-day data updates

## 4. Data Processing
- [ ] Set up SQLite database for history
- [ ] Convert 30min solar data to 15min intervals
- [ ] Calculate energy amounts (kWh)
- [ ] Calculate daily totals

## 5. Backend
- [ ] Create FastAPI routes
- [ ] Add data caching
- [ ] Add error handling
- [ ] Schedule data updates

## 6. Frontend
- [ ] Create simple web interface
- [ ] Show bar charts for:
  - [ ] Current day view
  - [ ] Next day view
- [ ] Add price overlay
- [ ] Make it mobile-friendly

## 7. Testing & Documentation
- [ ] Test core functionality
- [ ] Write setup instructions
- [ ] Add user guide

## 8. Deployment
- [ ] Test on Synology NAS
- [ ] Set up backups
- [ ] Document recovery steps 