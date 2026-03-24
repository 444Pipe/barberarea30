const servicesData = [
  {
    id: 1,
    name: 'Corte Básico',
    price: 30000,
    duration: 25,
    category: 'haircut',
    icon: '✂️',
    features: ['Incluye cejas', 'Styling con productos premium']
  },
  {
    id: 2,
    name: 'Corte + Freestyle',
    price: 35000,
    duration: 35,
    category: 'freestyle',
    icon: '🎨',
    features: ['Corte completo', 'Diseño freestyle personalizado', 'Cejas y styling'],
    popular: true
  },
  {
    id: 3,
    name: 'Corte con Barba',
    price: 40000,
    duration: 35,
    category: 'haircut',
    icon: '💈',
    features: ['Corte de cabello', 'Perfilado de barba', 'Cejas y styling']
  },
  {
    id: 4,
    name: 'Corte para Dama',
    price: 35000,
    duration: 40,
    category: 'haircut',
    icon: '👩',
    features: ['Corte personalizado', 'Limpieza de cejas con cuchilla']
  },
  {
    id: 5,
    name: 'Rayitos o Mechas',
    price: 225000,
    duration: 200,
    category: 'color',
    icon: '✨',
    features: ['Color profesional', 'Cuidado de color', 'Asesoría técnica']
  },
  {
    id: 6,
    name: 'Corte + Freestyle Creativo',
    price: 40000,
    duration: 45,
    category: 'freestyle',
    icon: '🎭',
    features: ['Diseño freestyle avanzado', 'Elementos creativos', 'Styling profesional']
  },
  {
    id: 7,
    name: 'Asesoría Visajista',
    price: 60000,
    duration: 60,
    category: 'consultation',
    icon: '👨‍💼',
    features: ['Análisis de rostro', 'Recomendación de corte', 'Corte + styling']
  },
  {
    id: 8,
    name: 'Trenzados',
    price: 70000,
    duration: 150,
    category: 'specialty',
    icon: '🧵',
    features: ['Trenzas personalizadas', 'Diseño a medida', 'Consulta incluida']
  }
];

export function getServices() {
  return servicesData;
}

export function getServiceById(id) {
  return servicesData.find(service => service.id === id);
}

export function getServicesByCategory(category) {
  return servicesData.filter(service => service.category === category);
}
