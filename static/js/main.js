document.addEventListener('DOMContentLoaded', () => {
    cargarServicios();
    cargarBarberos();
});

function cargarServicios() {
    fetch('/api/servicios-nativos/')
        .then(response => {
            if (!response.ok) throw new Error(`Error en servicios: ${response.status}`);
            return response.json();
        })
        .then(data => {
            const contenedor = document.getElementById('lista-servicios');
            if (!contenedor) return;
            let htmlFragment = '';
            
            data.servicios.forEach((servicio, index) => {
                const delay = index * 100;
                // Add comma separators to price
                const formatPrice = parseFloat(servicio.price).toLocaleString('es-CO');
                
                htmlFragment += `
                    <div class="service-card p-12 rounded-sm relative overflow-hidden group border border-white/5 bg-jet shadow-2xl transition-all duration-300 hover:border-gold/60" style="animation: fadeInUp 0.8s ease-out forwards; animation-delay: ${delay}ms; opacity: 0;">
                        <div class="flex justify-between items-start mb-8">
                            <h3 class="text-2xl font-serif text-white group-hover:text-gold transition-colors">${servicio.name}</h3>
                            <span class="text-gold font-medium tracking-widest">$${formatPrice}</span>
                        </div>
                        <p class="text-smoke/60 font-light text-sm mb-10 leading-relaxed italic">Duración: ${servicio.duration_minutes} min</p>
                        <a href="booking.html?service=${encodeURIComponent(servicio.name)}" class="text-gold text-xs tracking-widest uppercase font-bold hover:text-white transition-all flex items-center gap-3">Reserva VIP <span class="text-xl">→</span></a>
                    </div>
                `;
            });
            
            contenedor.innerHTML = htmlFragment;
        })
        .catch(error => console.error(error));
}

function cargarBarberos() {
    fetch('/api/barberos-nativos/')
        .then(response => {
            if (!response.ok) throw new Error(`Error en barberos: ${response.status}`);
            return response.json();
        })
        .then(data => {
            const contenedor = document.getElementById('lista-barberos');
            if (!contenedor) return;
            let htmlFragment = '';
            
            data.barberos.forEach((barbero, index) => {
                const delay = index * 100;
                
                htmlFragment += `
                    <div class="service-card p-10 rounded-sm relative overflow-hidden group border border-white/5 bg-jet transition-all duration-300 hover:border-gold/60 flex flex-col items-center text-center" style="animation: fadeInUp 0.8s ease-out forwards; animation-delay: ${delay}ms; opacity: 0;">
                        <!-- Icono SVG Placeholder -->
                        <div class="w-16 h-16 rounded-full border border-gold/40 flex items-center justify-center text-gold mb-6 group-hover:scale-110 transition-transform duration-500">
                             <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                             </svg>
                        </div>
                        <h3 class="text-2xl font-serif text-white group-hover:text-gold transition-colors mb-2">${barbero.nombre}</h3>
                        <div class="h-[1px] w-8 bg-gold/50 mx-auto my-3"></div>
                        <p class="text-smoke/60 font-light tracking-wide text-xs uppercase italic">${barbero.especialidad || 'Grooming Expert'}</p>
                    </div>
                `;
            });
            
            contenedor.innerHTML = htmlFragment;
        })
        .catch(error => console.error(error));
}

// Add simple fadeInUp keyframes if they don't exist
const styleSheet = document.createElement("style");
styleSheet.innerText = `
@keyframes fadeInUp {
    from {
        opacity: 0;
        transform: translateY(20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
`;
document.head.appendChild(styleSheet);
