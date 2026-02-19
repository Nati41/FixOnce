const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({ 
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  
  try {
    const page = await browser.newPage();
    
    // Collect all console messages with more detail
    const consoleLogs = [];
    page.on('console', msg => {
      consoleLogs.push({
        type: msg.type(),
        text: msg.text(),
        location: msg.location()
      });
    });
    
    // Collect network errors with URLs
    const networkErrors = [];
    page.on('requestfailed', request => {
      networkErrors.push({
        url: request.url(),
        method: request.method(),
        failure: request.failure()
      });
    });
    
    // Collect response errors (404, 500, etc)
    const responseErrors = [];
    page.on('response', response => {
      if (!response.ok()) {
        responseErrors.push({
          url: response.url(),
          status: response.status(),
          statusText: response.statusText()
        });
      }
    });
    
    console.log('Opening http://localhost:5000/v2...');
    await page.goto('http://localhost:5000/v2', { waitUntil: 'networkidle2' });
    
    // Wait a bit for any async content to load
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Get detailed dashboard state
    const dashboardState = await page.evaluate(() => {
      // Extract all visible metrics/numbers
      const extractNumbers = (text) => {
        const matches = text.match(/\d+/g);
        return matches ? matches.map(n => parseInt(n)) : [];
      };
      
      const body = document.body.innerText;
      
      // Try to find specific elements
      const nowCard = document.querySelector('.now-card, [data-card="now"]');
      const goalElement = document.querySelector('.goal, [data-section="goal"]');
      const decisionsElement = document.querySelector('.decisions, [data-stat="decisions"]');
      const resolvedElement = document.querySelector('.resolved, [data-stat="resolved"]');
      
      // Get all text content
      const lines = body.split('\n').map(l => l.trim()).filter(l => l.length > 0);
      
      return {
        nowCard: nowCard ? nowCard.innerText : 'not found',
        goal: goalElement ? goalElement.innerText : 'not found',
        decisions: decisionsElement ? decisionsElement.innerText : 'not found',
        resolved: resolvedElement ? resolvedElement.innerText : 'not found',
        allLines: lines,
        numbers: extractNumbers(body)
      };
    });
    
    console.log('\n=== DASHBOARD STATE ===');
    console.log('Now Card:', dashboardState.nowCard);
    console.log('\nKey Stats:');
    console.log('- Goal:', dashboardState.goal);
    console.log('- Decisions:', dashboardState.decisions);
    console.log('- Resolved:', dashboardState.resolved);
    console.log('\nAll visible lines:');
    dashboardState.allLines.forEach((line, i) => {
      if (i < 30) console.log(`  ${line}`);
    });
    console.log('\nNumbers found:', dashboardState.numbers);
    
    console.log('\n=== CONSOLE LOGS ===');
    consoleLogs.forEach(log => {
      console.log(`[${log.type}] ${log.text}`);
      if (log.location) console.log(`  Location: ${JSON.stringify(log.location)}`);
    });
    
    console.log('\n=== NETWORK ERRORS ===');
    if (networkErrors.length === 0) {
      console.log('None');
    } else {
      networkErrors.forEach(err => {
        console.log(`${err.method} ${err.url}`);
        console.log(`  Error: ${err.failure?.errorText || 'unknown'}`);
      });
    }
    
    console.log('\n=== RESPONSE ERRORS (404, 500, etc) ===');
    if (responseErrors.length === 0) {
      console.log('None');
    } else {
      responseErrors.forEach(err => {
        console.log(`${err.status} ${err.statusText}: ${err.url}`);
      });
    }
    
  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  } finally {
    await browser.close();
  }
})();
