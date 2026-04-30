cat > ~/gns3-web-ui/src/app/components/chat/chat.component.ts << 'EOF'
import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnInit, Output, OnDestroy } from '@angular/core';
import { ResizeEvent } from 'angular-resizable-element';
import { LinksDataSource } from 'app/cartography/datasources/links-datasource';
import { NodesDataSource } from 'app/cartography/datasources/nodes-datasource';
import { Subscription } from 'rxjs';
import { Node } from '../../cartography/models/node';
import { Link } from '../../models/link';
import { Project } from '../../models/project';
import { Server } from '../../models/server';
import { ProjectService } from '../../services/project.service';
import { ThemeService } from '../../services/theme.service';

@Component({
  selector: 'app-chat',
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.scss'],
  changeDetection: ChangeDetectionStrategy.Default,
})
export class ChatComponent implements OnInit, OnDestroy {
  @Input() server: Server;
  @Input() project: Project;
  @Output() closeChat = new EventEmitter<boolean>();

  public style = {};
  public bodyStyle = {};
  private subscriptions: Subscription[] = [];

  public inputValue: string = '';
  public isLoading: boolean = false;

  nodes: Node[] = [];
  links: Link[] = [];
  messages = [];

  isLightThemeEnabled: boolean = false;

  constructor(
    private nodeDataSource: NodesDataSource,
    private projectService: ProjectService,
    private linksDataSource: LinksDataSource,
    private themeService: ThemeService
  ) {}

  ngOnInit(): void {
    this.isLightThemeEnabled = this.themeService.getActualTheme() === 'light';

    this.subscriptions.push(
      this.nodeDataSource.changes.subscribe((nodes: Node[]) => {
        this.nodes = nodes.map(n => {
          if (['0.0.0.0', '0:0:0:0:0:0:0:0', '::'].includes(n.console_host)) {
            n.console_host = this.server.host;
          }
          return n;
        });
      })
    );

    this.subscriptions.push(
      this.linksDataSource.changes.subscribe((links: Link[]) => {
        this.links = links;
      })
    );

    this.revertPosition();

    this.messages.push({
      content: 'S-Witch LLM-NetConf pret ! Decrivez votre topologie ou tapez une commande reseau.',
      class: 'chatBody__message_other',
    });
  }

  revertPosition() {
    this.style = { position: 'fixed', bottom: '20px', right: '20px', width: '450px', height: '650px' };
    this.bodyStyle = { height: '510px' };
  }

  onResizeEnd(event: ResizeEvent): void {
    this.style = {
      position: 'fixed',
      left: `${event.rectangle.left}px`,
      top: `${event.rectangle.top}px`,
      width: `${event.rectangle.width}px`,
      height: `${event.rectangle.height}px`,
    };
    this.bodyStyle = { height: `${event.rectangle.height - 110}px` };
  }

  onKeyPress(event: KeyboardEvent) {
    if (event.key === 'Enter' && !this.isLoading) this.onClick();
  }

  onClick() {
    if (!this.inputValue?.trim() || this.isLoading) return;

    const userPrompt = this.inputValue;
    this.messages.push({ content: userPrompt, class: 'chatBody__message_me' });
    this.isLoading = true;
    this.inputValue = '';

    // Topologie avec ports consoles DYNAMIQUES
    const topology = {
      node_info: this.nodes.map(n => ({
        name: n.name,
        node_type: n.node_type,
        console: n.console,
        console_host: n.console_host,
        ports: n.ports || []
      })),
      link_info: this.links.map(l => ({
        link_id: l.link_id,
        nodes: l.nodes || []
      }))
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120000);

    fetch('http://localhost:8000/v4/invoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        input: {
          chat_history: [],
          topology: JSON.stringify(topology),
          question: userPrompt
        }
      })
    })
    .then(res => res.json())
    .then(data => {
      clearTimeout(timeoutId);
      const output = data.output || [];
      let response = 'Commandes generees :\n';
      output.forEach((item: any) => {
        if (item.device && item.command) {
          response += `\n[${item.device}]\n${item.command}\n`;
        }
      });
      this.messages.push({
        content: response,
        class: 'chatBody__message_other',
      });
    })
    .catch(err => {
      clearTimeout(timeoutId);
      this.messages.push({
        content: `Erreur: ${err.message}`,
        class: 'chatBody__message_other',
      });
    })
    .finally(() => {
      this.isLoading = false;
    });
  }

  ngOnDestroy() {
    this.subscriptions.forEach(s => s.unsubscribe());
  }
}
EOF