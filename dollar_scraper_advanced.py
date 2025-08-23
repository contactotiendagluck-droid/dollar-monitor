import requests
import json
import os
import re
from datetime import datetime
from bs4 import BeautifulSoup
import time

class DollarScraperMonitor:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.storage_file = 'scraped_prices.json'
        self.min_change_threshold = 5.0  # Pesos argentinos
        
        # Headers para evitar bloqueos
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        if not self.bot_token or not self.chat_id:
            raise ValueError("Variables TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID requeridas")
    
    def scrape_dolarhoy(self):
        """Scrapea cotizaciones desde DolarHoy.com"""
        cotizaciones = {}
        
        try:
            print("🌐 Scrapeando DolarHoy.com...")
            response = requests.get('https://dolarhoy.com/', 
                                  headers=self.headers, 
                                  timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Buscar contenedores de cotizaciones
            # DolarHoy estructura: div con clases específicas para cada tipo
            cotizacion_containers = soup.find_all('div', class_=['tile', 'cotizacion'])
            
            # También buscar por patrones específicos en el HTML
            # Patrón para dólar blue
            blue_match = re.search(r'Dólar blue.*?Compra.*?\$(\d+(?:,\d+)?).*?Venta.*?\$(\d+(?:,\d+)?)', 
                                 response.text, re.IGNORECASE | re.DOTALL)
            if blue_match:
                compra = float(blue_match.group(1).replace(',', ''))
                venta = float(blue_match.group(2).replace(',', ''))
                cotizaciones['Blue'] = {
                    'compra': compra,
                    'venta': venta,
                    'promedio': (compra + venta) / 2
                }
                print(f"   💙 Blue: Compra ${compra}, Venta ${venta}")
            
            # Patrón para dólar oficial
            oficial_match = re.search(r'Dólar oficial.*?Compra.*?\$(\d+(?:,\d+)?).*?Venta.*?\$(\d+(?:,\d+)?)', 
                                    response.text, re.IGNORECASE | re.DOTALL)
            if oficial_match:
                compra = float(oficial_match.group(1).replace(',', ''))
                venta = float(oficial_match.group(2).replace(',', ''))
                cotizaciones['Oficial'] = {
                    'compra': compra,
                    'venta': venta,
                    'promedio': (compra + venta) / 2
                }
                print(f"   🏛️ Oficial: Compra ${compra}, Venta ${venta}")
            
            # Buscar más tipos (MEP, CCL, etc.)
            mep_match = re.search(r'MEP.*?\$(\d+(?:,\d+)?)', 
                                response.text, re.IGNORECASE)
            if mep_match:
                precio = float(mep_match.group(1).replace(',', ''))
                cotizaciones['MEP'] = {
                    'compra': precio,
                    'venta': precio,
                    'promedio': precio
                }
                print(f"   📈 MEP: ${precio}")
            
            ccl_match = re.search(r'CCL.*?\$(\d+(?:,\d+)?)', 
                                response.text, re.IGNORECASE)
            if ccl_match:
                precio = float(ccl_match.group(1).replace(',', ''))
                cotizaciones['CCL'] = {
                    'compra': precio,
                    'venta': precio,
                    'promedio': precio
                }
                print(f"   🏦 CCL: ${precio}")
                
        except Exception as e:
            print(f"❌ Error scrapeando DolarHoy: {e}")
        
        return cotizaciones
    
    def scrape_finanzasargy(self):
        """Scrapea cotizaciones desde FinanzasArgy.com"""
        cotizaciones = {}
        
        try:
            print("🌐 Scrapeando FinanzasArgy.com...")
            response = requests.get('https://www.finanzasargy.com/', 
                                  headers=self.headers, 
                                  timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Buscar elementos que contengan precios
            # FinanzasArgy suele usar clases específicas para cada cotización
            price_elements = soup.find_all(['div', 'span', 'td'], 
                                         text=re.compile(r'\$\d+'))
            
            # Buscar patrones específicos en el texto
            # Dólar Blue
            blue_patterns = [
                r'Blue.*?\$(\d+(?:,\d+)?)',
                r'Informal.*?\$(\d+(?:,\d+)?)',
                r'Paralelo.*?\$(\d+(?:,\d+)?)'
            ]
            
            for pattern in blue_patterns:
                match = re.search(pattern, response.text, re.IGNORECASE)
                if match:
                    precio = float(match.group(1).replace(',', ''))
                    cotizaciones['Blue_FA'] = {
                        'compra': precio - 10,  # Estimación
                        'venta': precio + 10,
                        'promedio': precio
                    }
                    print(f"   💙 Blue (FA): ${precio}")
                    break
            
            # Dólar Oficial
            oficial_patterns = [
                r'Oficial.*?\$(\d+(?:,\d+)?)',
                r'BNA.*?\$(\d+(?:,\d+)?)'
            ]
            
            for pattern in oficial_patterns:
                match = re.search(pattern, response.text, re.IGNORECASE)
                if match:
                    precio = float(match.group(1).replace(',', ''))
                    cotizaciones['Oficial_FA'] = {
                        'compra': precio - 5,  # Estimación
                        'venta': precio + 5,
                        'promedio': precio
                    }
                    print(f"   🏛️ Oficial (FA): ${precio}")
                    break
            
            # Buscar más cotizaciones específicas
            solidario_match = re.search(r'Solidario.*?\$(\d+(?:,\d+)?)', 
                                      response.text, re.IGNORECASE)
            if solidario_match:
                precio = float(solidario_match.group(1).replace(',', ''))
                cotizaciones['Solidario'] = {
                    'compra': precio,
                    'venta': precio,
                    'promedio': precio
                }
                print(f"   💳 Solidario: ${precio}")
                
        except Exception as e:
            print(f"❌ Error scrapeando FinanzasArgy: {e}")
        
        return cotizaciones
    
    def get_all_prices(self):
        """Obtiene todas las cotizaciones de ambas fuentes"""
        all_prices = {}
        
        # Scrapear DolarHoy
        dolarhoy_prices = self.scrape_dolarhoy()
        all_prices.update(dolarhoy_prices)
        
        # Pequeña pausa entre requests
        time.sleep(2)
        
        # Scrapear FinanzasArgy
        finanzas_prices = self.scrape_finanzasargy()
        all_prices.update(finanzas_prices)
        
        return all_prices
    
    def load_last_prices(self):
        """Carga precios anteriores"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_prices(self, prices):
        """Guarda precios actuales"""
        data = {
            'prices': prices,
            'timestamp': datetime.now().isoformat(),
            'source': 'DolarHoy + FinanzasArgy'
        }
        
        with open(self.storage_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def send_telegram_message(self, message):
        """Envía mensaje por Telegram"""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                print("✅ Notificación enviada")
                return True
            else:
                print(f"❌ Error Telegram: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Error conexión Telegram: {e}")
            return False
    
    def format_comparison_message(self, changes):
        """Formatea mensaje con cambios detectados"""
        emoji_map = {
            'Blue': '💙',
            'Oficial': '🏛️',
            'MEP': '📈',
            'CCL': '🏦',
            'Solidario': '💳',
            'Blue_FA': '💙',
            'Oficial_FA': '🏛️'
        }
        
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        
        message_parts = ["🚨 <b>CAMBIOS EN COTIZACIONES DEL DÓLAR</b>\n"]
        
        for tipo, data in changes.items():
            emoji = emoji_map.get(tipo, '💰')
            old_price = data['old_price']
            new_price = data['new_price']
            change = new_price - old_price
            change_percent = (change / old_price) * 100
            
            direction_emoji = "📈" if change > 0 else "📉"
            direction_text = "SUBIÓ" if change > 0 else "BAJÓ"
            
            message_parts.append(f"""
{emoji} <b>{tipo.replace('_', ' ')}</b> {direction_emoji}
💰 Anterior: ${old_price:.2f}
💰 Actual: ${new_price:.2f}
📊 Cambio: ${change:+.2f} ({change_percent:+.1f}%)
<b>→ {direction_text}</b>
            """.strip())
        
        message_parts.append(f"\n🕐 <i>{timestamp}</i>")
        message_parts.append(f"📊 <i>Fuentes: DolarHoy + FinanzasArgy</i>")
        
        return "\n\n".join(message_parts)
    
    def check_and_notify(self):
        """Verificación principal"""
        print(f"🔍 Iniciando scraping - {datetime.now()}")
        
        # Obtener precios actuales
        current_prices = self.get_all_prices()
        
        if not current_prices:
            print("❌ No se pudieron obtener cotizaciones")
            return
        
        print(f"✅ Obtenidas {len(current_prices)} cotizaciones")
        
        # Cargar precios anteriores
        last_data = self.load_last_prices()
        last_prices = last_data.get('prices', {}) if last_data else {}
        
        # Detectar cambios significativos
        changes = {}
        
        for tipo, cotizacion in current_prices.items():
            current_price = cotizacion['promedio']
            
            if tipo in last_prices:
                last_price = last_prices[tipo]['promedio']
                change = abs(current_price - last_price)
                
                if change >= self.min_change_threshold:
                    changes[tipo] = {
                        'old_price': last_price,
                        'new_price': current_price
                    }
                    print(f"🚨 {tipo}: ${last_price:.2f} → ${current_price:.2f} ({change:+.2f})")
                else:
                    print(f"📊 {tipo}: ${current_price:.2f} (sin cambios significativos)")
            else:
                # Primera vez - solo informar
                print(f"🆕 {tipo}: ${current_price:.2f} (precio inicial)")
        
        # Enviar notificaciones si hay cambios
        if changes:
            message = self.format_comparison_message(changes)
            self.send_telegram_message(message)
        elif not last_prices:
            # Mensaje de inicio
            precio_info = []
            for tipo, cotizacion in current_prices.items():
                precio_info.append(f"{tipo}: ${cotizacion['promedio']:.2f}")
            
            inicio_message = f"""
🚀 <b>Monitor de Dólar Iniciado</b>

📊 <b>Cotizaciones actuales:</b>
{chr(10).join(precio_info)}

Te notificaré cuando haya cambios ≥ ${self.min_change_threshold:.0f}

🕐 <i>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</i>
            """.strip()
            
            self.send_telegram_message(inicio_message)
        else:
            print("😴 Sin cambios significativos detectados")
        
        # Guardar precios actuales
        self.save_prices(current_prices)
        print("💾 Precios guardados exitosamente")

def main():
    """Función principal para GitHub Actions"""
    try:
        monitor = DollarScraperMonitor()
        monitor.check_and_notify()
    except Exception as e:
        print(f"❌ Error fatal: {e}")
        # Enviar error por Telegram si es posible
        if 'TELEGRAM_BOT_TOKEN' in os.environ and 'TELEGRAM_CHAT_ID' in os.environ:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
                    data={
                        'chat_id': os.getenv('TELEGRAM_CHAT_ID'),
                        'text': f"❌ <b>Error en Monitor de Dólar</b>\n\n{str(e)}",
                        'parse_mode': 'HTML'
                    },
                    timeout=10
                )
            except:
                pass

if __name__ == "__main__":
    print("🕷️ MONITOR DE DÓLAR CON WEB SCRAPING")
    print("📊 Fuentes: DolarHoy.com + FinanzasArgy.com")
    print("=" * 50)
    main()
