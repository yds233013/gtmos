import type { AuditResponse, HubspotMapping, Integration, ReverseEtlPreview, SimulatedObjects } from "@/components/insights/types";
import { DemoBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, settle } from "@/lib/api";
import type { Workspace } from "@/lib/types";

import { AuditSection } from "./audit-section";
import { MappingSection, ReverseEtlSection } from "./hubspot-section";
import { IntegrationsSection } from "./integrations-section";

export const metadata = { title: "Settings" };

const TABS = ["integrations", "hubspot", "reverse-etl", "audit"] as const;

function one(v: string | string[] | undefined): string | undefined {
  const s = Array.isArray(v) ? v[0] : v;
  return s && s.trim() ? s.trim() : undefined;
}

export default async function SettingsPage(props: PageProps<"/settings">) {
  const sp = await props.searchParams;
  const tabParam = one(sp.tab);
  const tab = TABS.find((t) => t === tabParam) ?? "integrations";
  const action = one(sp.action);
  const actorType = one(sp.actor_type);

  const auditQs = new URLSearchParams({ limit: "100" });
  if (action) auditQs.set("action", action);
  if (actorType) auditQs.set("actor_type", actorType);

  const [ws, integrations, mapping, preview, objects, audit] = await settle(
    api<Workspace & { outbound_send_enabled?: boolean }>("/workspace"),
    api<Integration[]>("/integrations"),
    api<HubspotMapping>("/integrations/hubspot/mapping"),
    api<ReverseEtlPreview>("/integrations/hubspot/reverse-etl/preview?limit=10"),
    api<SimulatedObjects>("/integrations/hubspot/simulated-objects?object_type=companies&limit=20"),
    api<AuditResponse>(`/audit?${auditQs.toString()}`),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Settings"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            {ws?.name ?? "Workspace"} {ws?.mode !== "live" && <DemoBadge />}
          </span>
        }
        description="Integrations and what it takes to make each one live, the HubSpot data contract, the reverse-ETL sync, and the audit trail of every write."
      />

      <Tabs defaultValue={tab}>
        <TabsList aria-label="Settings sections">
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="hubspot">HubSpot mapping</TabsTrigger>
          <TabsTrigger value="reverse-etl">Reverse ETL</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
        </TabsList>
        <TabsContent value="integrations">
          {integrations ? (
            <IntegrationsSection integrations={integrations} ws={ws} />
          ) : (
            <ErrorState title="Couldn't load integrations" message="The integrations endpoint failed." />
          )}
        </TabsContent>
        <TabsContent value="hubspot">
          <MappingSection mapping={mapping} />
        </TabsContent>
        <TabsContent value="reverse-etl">
          <ReverseEtlSection preview={preview} objects={objects} />
        </TabsContent>
        <TabsContent value="audit">
          <AuditSection audit={audit} action={action} actorType={actorType} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
