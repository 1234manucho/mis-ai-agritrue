document.addEventListener('DOMContentLoaded', function () {
    fetch('/api/chart-data')
      .then((response) => response.json())
      .then((data) => {
        // Soil Chart
        const soilLabels = Object.keys(data.soil_by_county);
        const soilDatasets = [];
  
        soilLabels.forEach((county, i) => {
          const types = data.soil_by_county[county];
          types.forEach((type) => {
            let dataset = soilDatasets.find((d) => d.label === type.soil_type);
            if (!dataset) {
              dataset = {
                label: type.soil_type,
                data: Array(soilLabels.length).fill(0),
                backgroundColor: getRandomColor(),
              };
              soilDatasets.push(dataset);
            }
            dataset.data[i] = type.count;
          });
        });
  
        new Chart(document.getElementById('soilChart'), {
          type: 'bar',
          data: {
            labels: soilLabels,
            datasets: soilDatasets,
          },
          options: {
            responsive: true,
            plugins: {
              title: { display: true, text: 'Soil Types by County' },
            },
          },
        });
  
        // Pest Chart
        const pestLabels = Object.keys(data.pests_by_region);
        const pestDatasets = [];
  
        pestLabels.forEach((region, i) => {
          const pests = data.pests_by_region[region];
          pests.forEach((p) => {
            let dataset = pestDatasets.find((d) => d.label === p.pest_type);
            if (!dataset) {
              dataset = {
                label: p.pest_type,
                data: Array(pestLabels.length).fill(0),
                backgroundColor: getRandomColor(),
              };
              pestDatasets.push(dataset);
            }
            dataset.data[i] = p.count;
          });
        });
  
        new Chart(document.getElementById('pestChart'), {
          type: 'bar',
          data: {
            labels: pestLabels,
            datasets: pestDatasets,
          },
          options: {
            responsive: true,
            plugins: {
              title: { display: true, text: 'Pest Types by Region' },
            },
          },
        });
  
        // Innovation Chart
        const innovLabels = Object.keys(data.innovations_by_county);
        const innovDatasets = [];
  
        innovLabels.forEach((county, i) => {
          const innovations = data.innovations_by_county[county];
          innovations.forEach((inn) => {
            let dataset = innovDatasets.find((d) => d.label === inn.innovation);
            if (!dataset) {
              dataset = {
                label: inn.innovation,
                data: Array(innovLabels.length).fill(0),
                backgroundColor: getRandomColor(),
              };
              innovDatasets.push(dataset);
            }
            dataset.data[i] = inn.count;
          });
        });
  
        new Chart(document.getElementById('innovationChart'), {
          type: 'bar',
          data: {
            labels: innovLabels,
            datasets: innovDatasets,
          },
          options: {
            responsive: true,
            plugins: {
              title: { display: true, text: 'Innovations by County' },
            },
          },
        });
  
        // Weed Chart
        const weedLabels = Object.keys(data.weeds_by_region);
        const weedDatasets = [];
  
        weedLabels.forEach((region, i) => {
          const weeds = data.weeds_by_region[region];
          weeds.forEach((w) => {
            let dataset = weedDatasets.find((d) => d.label === w.weed_type);
            if (!dataset) {
              dataset = {
                label: w.weed_type,
                data: Array(weedLabels.length).fill(0),
                backgroundColor: getRandomColor(),
              };
              weedDatasets.push(dataset);
            }
            dataset.data[i] = w.count;
          });
        });
  
        new Chart(document.getElementById('weedChart'), {
          type: 'pie',
          data: {
            labels: weedLabels,
            datasets: weedDatasets,
          },
          options: {
            responsive: true,
            plugins: {
              title: { display: true, text: 'Weed Types by Region' },
            },
          },
        });
  
        // Altitude Chart
        const altitudeLabels = Object.keys(data.altitude_by_county);
        const altitudeData = altitudeLabels.map(
          (county) => data.altitude_by_county[county].altitude
        );
  
        new Chart(document.getElementById('altitudeChart'), {
          type: 'bar',
          data: {
            labels: altitudeLabels,
            datasets: [
              {
                label: 'Altitude',
                data: altitudeData,
                backgroundColor: getRandomColor(),
              },
            ],
          },
          options: {
            responsive: true,
            plugins: {
              title: { display: true, text: 'Altitude by County' },
            },
          },
        });
  
        // Weather Chart
        const weatherLabels = Object.keys(data.weather_by_county);
        const weatherData = weatherLabels.map(
          (county) => data.weather_by_county[county].temperature
        );
  
        new Chart(document.getElementById('weatherChart'), {
          type: 'line',
          data: {
            labels: weatherLabels,
            datasets: [
              {
                label: 'Temperature',
                data: weatherData,
                borderColor: getRandomColor(),
                fill: false,
              },
            ],
          },
          options: {
            responsive: true,
            plugins: {
              title: { display: true, text: 'Weather by County' },
            },
          },
        });
      })
      .catch((err) => console.error('Chart Data Error:', err));
  });
  
  function getRandomColor() {
    const letters = '0123456789ABCDEF';
    let color = '#';
    for (let i = 0; i < 6; i++) {
      color += letters[Math.floor(Math.random() * 16)];
    }
    return color;
  }
  new Chart(document.getElementById("chart_{{ col }}").getContext("2d"), {
    type: "{{ 'bar' if values.min is undefined else 'line' }}",
    data: {
        labels: Object.keys(values),
        datasets: [{
            label: '{{ col }}',
            data: values.values(),
            backgroundColor: 'rgba(75, 192, 192, 0.4)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1,
        }]
    },
    options: { responsive: true }
});
