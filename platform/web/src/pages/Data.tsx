// 数据浏览页：联系方式 / 店铺 / FB·X 三个 Tab 的只读分页浏览
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PageHeader } from '@/components/PageState'
import { ContactsTab } from './data/ContactsTab'
import { ShopsTab } from './data/ShopsTab'
import { FbTab } from './data/FbTab'

export function DataPage() {
  return (
    <div className="p-6">
      <PageHeader title="数据浏览" desc="已采集的店铺与联系方式，支持筛选与分页浏览" />
      <Tabs defaultValue="contacts">
        <TabsList>
          <TabsTrigger value="contacts">联系方式</TabsTrigger>
          <TabsTrigger value="shops">店铺</TabsTrigger>
          <TabsTrigger value="facebook">FB / X</TabsTrigger>
        </TabsList>
        <TabsContent value="contacts">
          <ContactsTab />
        </TabsContent>
        <TabsContent value="shops">
          <ShopsTab />
        </TabsContent>
        <TabsContent value="facebook">
          <FbTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
